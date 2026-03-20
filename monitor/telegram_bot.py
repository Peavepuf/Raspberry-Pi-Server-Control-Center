from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

from monitor.reporting import (
    build_daily_summary,
    build_servers_message,
    build_status_message,
    build_uptime_message,
    build_weekly_summary,
    chunk_message,
)

LOGGER = logging.getLogger(__name__)


class TelegramBotClient:
    def __init__(self, token: str) -> None:
        self.update_token(token)

    def update_token(self, token: str) -> None:
        self.token = token.strip()
        self.base_url = f"https://api.telegram.org/bot{self.token}" if self.token else ""

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def _request(self, method: str, payload: dict[str, object] | None = None, timeout: int = 60) -> dict[str, object]:
        if not self.enabled:
            raise RuntimeError("Telegram bot token is not configured.")

        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            url=f"{self.base_url}/{method}",
            data=data,
            headers=headers,
            method="POST" if payload is not None else "GET",
        )

        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")

        parsed = json.loads(raw)
        if not parsed.get("ok"):
            raise RuntimeError(f"Telegram API error: {parsed}")
        return parsed

    def send_message(self, chat_id: str, text: str) -> None:
        for part in chunk_message(text):
            self._request(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": part,
                },
                timeout=30,
            )

    def get_updates(self, offset: int | None = None, timeout: int = 30) -> list[dict[str, object]]:
        query = {"timeout": timeout}
        if offset is not None:
            query["offset"] = offset
        query_string = urllib.parse.urlencode(query)
        response = self._request(f"getUpdates?{query_string}", timeout=timeout + 10)
        return list(response.get("result", []))


class TelegramPoller(threading.Thread):
    def __init__(
        self,
        *,
        bot: TelegramBotClient,
        database,
        get_report: Callable[[], dict[str, object]],
        get_daily_report: Callable[[], dict[str, object]],
        get_weekly_report: Callable[[], dict[str, object]],
        auto_register_chats: bool,
        stop_event: threading.Event,
    ) -> None:
        super().__init__(daemon=True)
        self.bot = bot
        self.database = database
        self.get_report = get_report
        self.get_daily_report = get_daily_report
        self.get_weekly_report = get_weekly_report
        self.auto_register_chats = auto_register_chats
        self.stop_event = stop_event

    def run(self) -> None:
        offset = int(self.database.get_state("telegram_offset", "0") or "0")
        while not self.stop_event.is_set():
            if not self.bot.enabled:
                self.stop_event.wait(3)
                continue
            try:
                updates = self.bot.get_updates(offset=offset, timeout=25)
                for update in updates:
                    offset = int(update["update_id"]) + 1
                    self.database.set_state("telegram_offset", str(offset))
                    self._handle_update(update)
            except urllib.error.URLError as exc:
                LOGGER.warning("Telegram connection error: %s", exc)
                self.stop_event.wait(10)
            except Exception as exc:
                LOGGER.exception("Failed to process Telegram update: %s", exc)
                self.stop_event.wait(10)

    def _handle_update(self, update: dict[str, object]) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return

        chat = message.get("chat")
        text = str(message.get("text", "")).strip()
        if not isinstance(chat, dict):
            return

        chat_id = str(chat.get("id", "")).strip()
        title = (
            str(chat.get("title", "")).strip()
            or " ".join(
                part
                for part in [str(chat.get("first_name", "")).strip(), str(chat.get("last_name", "")).strip()]
                if part
            )
            or str(chat.get("username", "")).strip()
        )

        if self.auto_register_chats and chat_id:
            self.database.add_chat(chat_id, title=title or None)

        if not text.startswith("/"):
            return

        report = self.get_report()
        if text.startswith("/start"):
            reply = "Bot activated. This chat has been registered for scheduled reports."
        elif text.startswith("/help"):
            reply = "/start\n/help\n/status\n/uptime\n/servers\n/daily\n/weekly"
        elif text.startswith("/status"):
            reply = build_status_message(report)
        elif text.startswith("/uptime"):
            reply = build_uptime_message(report)
        elif text.startswith("/servers"):
            reply = build_servers_message(report)
        elif text.startswith("/daily"):
            reply = build_daily_summary(self.get_daily_report())
        elif text.startswith("/weekly"):
            reply = build_weekly_summary(self.get_weekly_report())
        else:
            reply = "Unknown command. Use /help."

        try:
            self.bot.send_message(chat_id, reply)
        except Exception as exc:
            LOGGER.warning("Failed to send Telegram reply (%s): %s", chat_id, exc)
