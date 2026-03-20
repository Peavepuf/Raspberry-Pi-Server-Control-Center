from __future__ import annotations

import argparse
import logging
import signal
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from monitor.checker import ping_server
from monitor.config import load_app_config, load_servers
from monitor.database import Database
from monitor.fan_control import TemperatureFanController
from monitor.i18n import normalize_language, tr
from monitor.models import CheckResult, FanSettings, ServerConfig
from monitor.reporting import (
    build_daily_summary,
    build_hourly_summary,
    build_ssl_warning_message,
    build_state_change_message,
    build_weekly_summary,
)
from monitor.telegram_bot import TelegramBotClient, TelegramPoller

LOGGER = logging.getLogger(__name__)
SSL_WARNING_THRESHOLDS = [0, 1, 3, 7, 15, 30]


@dataclass(slots=True)
class ScheduledJob:
    name: str
    description: str
    next_run: datetime
    next_run_factory: Callable[[datetime], datetime]
    action: Callable[[], None]

    def schedule_next(self, now: datetime) -> None:
        self.next_run = self.next_run_factory(now)


def _next_hour_boundary(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


def _next_daily_time(now: datetime, hour: int, minute: int) -> datetime:
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _next_weekly_time(now: datetime, weekday: int, hour: int, minute: int) -> datetime:
    days_ahead = (weekday - now.weekday()) % 7
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=days_ahead)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


class MonitorApplication:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.config = load_app_config(base_dir)
        self.database = Database(self.config.database_path)

        try:
            default_servers = load_servers(self.config.server_config_path)
        except FileNotFoundError:
            default_servers = []

        self.database.seed_servers_if_empty(default_servers)
        self.database.ensure_fan_settings(self.config.fan_settings)
        self.database.ensure_telegram_settings(
            self.config.telegram_bot_token,
            self.config.telegram_chat_ids,
        )
        if self.database.get_state("ui_language") is None:
            self.database.set_state("ui_language", "en")

        telegram_settings = self.database.get_telegram_settings()
        self.bot = TelegramBotClient(str(telegram_settings["token"]))
        self.fan_controller = TemperatureFanController(self.database.get_fan_settings())

        self.stop_event = threading.Event()
        self.poller: TelegramPoller | None = None
        self.scheduler_thread: threading.Thread | None = None
        self._task_lock = threading.Lock()
        self._jobs_lock = threading.Lock()
        self._jobs: list[ScheduledJob] = []
        self._components_started = False

        if not self.database.list_servers(enabled_only=False):
            LOGGER.warning("No servers are currently configured in the database.")

    def start_background_components(self) -> None:
        if self._components_started:
            return
        self._components_started = True
        self.start_poller()
        self.fan_controller.start()

    def start_poller(self) -> None:
        if not self.bot.enabled:
            LOGGER.warning("Telegram token is not configured. Notifications are disabled.")
            return
        if self.poller and self.poller.is_alive():
            return

        self.poller = TelegramPoller(
            bot=self.bot,
            database=self.database,
            get_report=self.database.get_uptime_report,
            get_daily_report=lambda: self.database.get_period_report(24),
            get_weekly_report=lambda: self.database.get_period_report(24 * 7),
            auto_register_chats=self.config.auto_register_chats,
            get_language=self.get_language,
            stop_event=self.stop_event,
        )
        self.poller.start()

    def start_scheduler_thread(self) -> None:
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            return

        self.scheduler_thread = threading.Thread(
            target=self.run_scheduler_loop,
            kwargs={"install_signal_handlers": False},
            name="monitor-scheduler",
            daemon=True,
        )
        self.scheduler_thread.start()

    def discover_chat_ids(self) -> int:
        self.start_background_components()
        LOGGER.info("If you sent /start to the bot, the chat ID should be stored within a few seconds.")
        time.sleep(8)
        self.stop()

        chats = self.database.get_discovered_chats()
        if not chats:
            print("No chat was discovered yet. Send /start to the bot in Telegram and try again.")
            return 1

        print("Discovered chat records:")
        for chat in chats:
            title = f" ({chat['title']})" if chat["title"] else ""
            print(f"- {chat['chat_id']}{title} - {chat['discovered_at']}")
        return 0

    def run_once(self, send_notification: bool = True, title: str | None = None) -> None:
        with self._task_lock:
            lang = self.get_language()
            previous_states = self.database.get_latest_status_map()
            results = self._check_servers()
            report = self.database.get_uptime_report()

            if send_notification:
                changes = self._build_state_changes(previous_states, results)
                if changes:
                    self._notify_all(build_state_change_message(changes, lang=lang))

                ssl_warnings = self._collect_ssl_warnings(results)
                if ssl_warnings:
                    self._notify_all(build_ssl_warning_message(ssl_warnings, lang=lang))

            message = build_hourly_summary(report, title=title or tr(lang, "one_time_server_report"), lang=lang)
            LOGGER.info("\n%s", message)
            if send_notification:
                self._notify_all(message)

    def run_daily_summary(self, send_notification: bool = True) -> None:
        with self._task_lock:
            lang = self.get_language()
            report = self.database.get_period_report(24)
            message = build_daily_summary(report, lang=lang)
            LOGGER.info("\n%s", message)
            if send_notification:
                self._notify_all(message)

    def run_weekly_summary(self, send_notification: bool = True) -> None:
        with self._task_lock:
            lang = self.get_language()
            report = self.database.get_period_report(24 * 7)
            message = build_weekly_summary(report, lang=lang)
            LOGGER.info("\n%s", message)
            if send_notification:
                self._notify_all(message)

    def run_scheduler_loop(self, install_signal_handlers: bool = True) -> None:
        self.start_background_components()
        if install_signal_handlers:
            self._install_signal_handlers()

        if self.config.run_on_start:
            self.run_once(send_notification=True, title=self._t("startup_server_report"))

        jobs = self._build_jobs()
        with self._jobs_lock:
            self._jobs = jobs

        while not self.stop_event.is_set():
            next_job = min(jobs, key=lambda item: item.next_run)
            now = datetime.now()
            sleep_seconds = max(1, int((next_job.next_run - now).total_seconds()))
            LOGGER.info(
                "Next scheduled job: %s (%s) | in %s seconds | %s",
                next_job.name,
                next_job.description,
                sleep_seconds,
                next_job.next_run.strftime("%Y-%m-%d %H:%M:%S"),
            )

            if self.stop_event.wait(sleep_seconds):
                break

            execution_time = datetime.now()
            due_jobs = [job for job in jobs if job.next_run <= execution_time]
            for job in sorted(due_jobs, key=lambda item: item.next_run):
                LOGGER.info("Running scheduled job: %s", job.name)
                try:
                    job.action()
                except Exception as exc:
                    LOGGER.exception("Scheduled job failed (%s): %s", job.name, exc)
                finally:
                    job.schedule_next(datetime.now() + timedelta(seconds=1))
                    with self._jobs_lock:
                        self._jobs = jobs

    def run_gui(self) -> int:
        try:
            from monitor.gui import MonitorDashboard

            dashboard = MonitorDashboard(self)
            return dashboard.run()
        except Exception as exc:
            LOGGER.exception("Failed to start the Tkinter interface: %s", exc)
            LOGGER.error("You can start the application with --headless if needed.")
            return 1

    def get_dashboard_snapshot(self) -> dict[str, object]:
        language = self.get_language()
        report = self.database.get_uptime_report()
        fan = self.fan_controller.get_status()
        fan_settings = self.database.get_fan_settings()
        telegram_settings = self.database.get_telegram_settings()
        servers = self.database.list_servers(enabled_only=False)
        with self._jobs_lock:
            jobs = [
                {
                    "name": job.name,
                    "description": job.description,
                    "next_run": job.next_run.strftime("%Y-%m-%d %H:%M:%S"),
                }
                for job in sorted(self._jobs, key=lambda item: item.next_run)
            ]
        return {
            "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "report": report,
            "fan": fan,
            "fan_settings": fan_settings,
            "telegram_settings": telegram_settings,
            "servers_config": servers,
            "jobs": jobs,
            "language": language,
        }

    def list_servers(self) -> list[ServerConfig]:
        return self.database.list_servers(enabled_only=False)

    def save_server(self, *, name: str, address: str, enabled: bool = True, server_id: int | None = None) -> tuple[bool, str]:
        name = name.strip()
        address = self._normalize_address(address)
        if not name or not address:
            return False, self._t("server_name_address_required")

        try:
            self.database.save_server(name=name, address=address, enabled=enabled, server_id=server_id)
        except sqlite3.IntegrityError:
            return False, self._t("server_duplicate")
        return True, self._t("server_saved")

    def _normalize_address(self, value: str) -> str:
        raw = value.strip()
        if not raw:
            return ""
        return raw.rstrip("/")

    def delete_server(self, server_id: int) -> tuple[bool, str]:
        self.database.delete_server(server_id)
        return True, self._t("server_deleted")

    def get_fan_settings(self) -> FanSettings:
        return self.database.get_fan_settings()

    def save_fan_settings(
        self,
        *,
        pin: int,
        min_temp_c: float,
        max_temp_c: float,
        poll_interval_seconds: int,
    ) -> tuple[bool, str]:
        if min_temp_c >= max_temp_c:
            return False, self._t("fan_temp_validation")
        if poll_interval_seconds < 2:
            return False, self._t("fan_interval_validation")

        settings = FanSettings(
            pin=pin,
            min_temp_c=min_temp_c,
            max_temp_c=max_temp_c,
            poll_interval_seconds=poll_interval_seconds,
            min_speed_percent=25,
            max_speed_percent=100,
        )
        self.database.save_fan_settings(settings)
        self.fan_controller.update_settings(settings)
        return True, self._t("fan_saved")

    def get_telegram_settings(self) -> dict[str, object]:
        return self.database.get_telegram_settings()

    def save_telegram_settings(self, *, token: str, chat_ids_raw: str) -> tuple[bool, str]:
        clean_token = token.strip()
        clean_chat_ids = [item.strip() for item in chat_ids_raw.split(",") if item.strip()]
        self.database.save_telegram_settings(clean_token, clean_chat_ids)
        self.bot.update_token(clean_token)
        if clean_token and self._components_started:
            self.start_poller()
        return True, self._t("telegram_saved")

    def get_language(self) -> str:
        return normalize_language(self.database.get_state("ui_language", "en"))

    def save_language(self, language: str) -> tuple[bool, str]:
        if (language or "").strip().lower() not in {"en", "tr"}:
            return False, self._t("language_invalid")
        normalized = normalize_language(language)
        self.database.set_state("ui_language", normalized)
        return True, tr(normalized, "language_saved")

    def send_test_telegram_message(self) -> tuple[bool, str]:
        lang = self.get_language()
        if not self.bot.enabled:
            return False, tr(lang, "telegram_token_missing")

        chat_ids = self._get_notification_chat_ids()
        if not chat_ids:
            return False, tr(lang, "telegram_chat_missing")

        message = (
            f"✅ {tr(lang, 'telegram_test_message')}\n"
            f"{tr(lang, 'telegram_ready')}\n"
            f"{tr(lang, 'generated_at', value=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}"
        )
        sent_count, errors = self._send_message_to_chats(chat_ids, message)
        if sent_count == 0:
            return False, tr(lang, "telegram_test_failed", error="; ".join(errors or [tr(lang, "unknown")]))
        if errors:
            return True, tr(lang, "telegram_test_partial", count=sent_count, error="; ".join(errors))
        return True, tr(lang, "telegram_test_success", count=sent_count)

    def _build_jobs(self) -> list[ScheduledJob]:
        now = datetime.now()
        return [
            ScheduledJob(
                name="hourly_check",
                description=self._t("hourly_connectivity_check"),
                next_run=_next_hour_boundary(now),
                next_run_factory=_next_hour_boundary,
                action=lambda: self.run_once(send_notification=True, title=self._t("hourly_server_report")),
            ),
            ScheduledJob(
                name="daily_summary",
                description=self._t("daily_summary_report"),
                next_run=_next_daily_time(now, self.config.daily_report_hour, self.config.daily_report_minute),
                next_run_factory=lambda current: _next_daily_time(
                    current,
                    self.config.daily_report_hour,
                    self.config.daily_report_minute,
                ),
                action=lambda: self.run_daily_summary(send_notification=True),
            ),
            ScheduledJob(
                name="weekly_summary",
                description=self._t("weekly_summary_report"),
                next_run=_next_weekly_time(
                    now,
                    self.config.weekly_report_weekday,
                    self.config.weekly_report_hour,
                    self.config.weekly_report_minute,
                ),
                next_run_factory=lambda current: _next_weekly_time(
                    current,
                    self.config.weekly_report_weekday,
                    self.config.weekly_report_hour,
                    self.config.weekly_report_minute,
                ),
                action=lambda: self.run_weekly_summary(send_notification=True),
            ),
        ]

    def _get_active_servers(self) -> list[ServerConfig]:
        return self.database.list_servers(enabled_only=True)

    def _check_servers(self) -> list[CheckResult]:
        results: list[CheckResult] = []
        for server in self._get_active_servers():
            result = ping_server(
                server,
                ping_binary=self.config.ping_binary,
                timeout_seconds=self.config.ping_timeout_seconds,
                count=self.config.ping_count,
            )
            self.database.add_check_result(result)
            results.append(result)
        return results

    def _collect_ssl_warnings(self, results: list[CheckResult]) -> list[dict[str, object]]:
        warnings: list[dict[str, object]] = []
        for result in results:
            threshold = self._resolve_ssl_warning_threshold(result.ssl_days_left)
            state_key = f"ssl_warning::{result.server_name}"
            previous_threshold = self.database.get_state(state_key, "") or ""

            if threshold is None:
                if previous_threshold:
                    self.database.set_state(state_key, "")
                continue

            threshold_value = str(threshold)
            if previous_threshold == threshold_value:
                continue

            self.database.set_state(state_key, threshold_value)
            warnings.append(
                {
                    "name": result.server_name,
                    "address": result.address,
                    "days_left": result.ssl_days_left,
                    "expires_at": result.ssl_expires_at or "unknown",
                    "expired": isinstance(result.ssl_days_left, int) and result.ssl_days_left < 0,
                }
            )
        return warnings

    def _resolve_ssl_warning_threshold(self, ssl_days_left: int | None) -> int | None:
        if not isinstance(ssl_days_left, int):
            return None
        for threshold in SSL_WARNING_THRESHOLDS:
            if ssl_days_left <= threshold:
                return threshold
        return None

    def _build_state_changes(
        self,
        previous_states: dict[str, bool | None],
        results: list[CheckResult],
    ) -> list[dict[str, object]]:
        changes: list[dict[str, object]] = []
        for result in results:
            previous = previous_states.get(result.server_name)
            if previous is None or previous == result.is_up:
                continue
            changes.append(
                {
                    "name": result.server_name,
                    "address": result.address,
                    "is_up": result.is_up,
                    "error": result.error,
                }
            )
        return changes

    def _notify_all(self, message: str) -> None:
        if not self.bot.enabled or not message.strip():
            return

        chat_ids = self._get_notification_chat_ids()
        if not chat_ids:
            LOGGER.warning("No Telegram chat is configured. Send /start to the bot or add a chat ID in settings.")
            return

        _, errors = self._send_message_to_chats(chat_ids, message)
        for error in errors:
            LOGGER.warning(error)

    def _get_notification_chat_ids(self) -> list[str]:
        chat_ids: list[str] = []
        seen: set[str] = set()
        telegram_settings = self.database.get_telegram_settings()
        configured_chat_ids = list(telegram_settings["chat_ids"])
        for chat_id in [*configured_chat_ids, *self.database.get_active_chat_ids()]:
            if chat_id and chat_id not in seen:
                seen.add(chat_id)
                chat_ids.append(chat_id)
        return chat_ids

    def _send_message_to_chats(self, chat_ids: list[str], message: str) -> tuple[int, list[str]]:
        sent_count = 0
        errors: list[str] = []
        for chat_id in chat_ids:
            try:
                self.bot.send_message(chat_id, message)
                sent_count += 1
            except Exception as exc:
                errors.append(f"Failed to send Telegram notification ({chat_id}): {exc}")
        return sent_count, errors

    def _install_signal_handlers(self) -> None:
        def _handle_signal(signum, _frame) -> None:
            LOGGER.info("Shutdown signal received (%s).", signum)
            self.stop()

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, _handle_signal)

    def stop(self) -> None:
        self.stop_event.set()
        self.fan_controller.stop()
        if self.poller and self.poller.is_alive():
            self.poller.join(timeout=2)
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            self.scheduler_thread.join(timeout=2)

    def _t(self, key: str, **kwargs: object) -> str:
        return tr(self.get_language(), key, **kwargs)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Raspberry Pi Server Control Center")
    parser.add_argument("--run-once", action="store_true", help="Run a single check and exit")
    parser.add_argument("--run-daily", action="store_true", help="Generate the daily summary and exit")
    parser.add_argument("--run-weekly", action="store_true", help="Generate the weekly summary and exit")
    parser.add_argument("--no-notify", action="store_true", help="Do not send Telegram notifications")
    parser.add_argument("--headless", action="store_true", help="Run without launching the GUI")
    parser.add_argument("--gui", action="store_true", help="Launch with the Tkinter interface")
    parser.add_argument(
        "--discover-chat-id",
        action="store_true",
        help="Show chat IDs discovered through Telegram",
    )
    return parser


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def main() -> int:
    configure_logging()
    args = build_arg_parser().parse_args()
    app = MonitorApplication(Path(__file__).resolve().parent.parent)

    try:
        send_notification = not args.no_notify
        if args.discover_chat_id:
            return app.discover_chat_ids()
        if args.run_daily:
            app.run_daily_summary(send_notification=send_notification)
            return 0
        if args.run_weekly:
            app.run_weekly_summary(send_notification=send_notification)
            return 0
        if args.run_once:
            app.run_once(send_notification=send_notification)
            return 0
        if args.headless:
            app.run_scheduler_loop(install_signal_handlers=True)
            return 0
        return app.run_gui()
    finally:
        app.stop()
        app.database.close()
