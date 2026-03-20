from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from monitor.models import FanSettings, ServerConfig

EMBEDDED_TELEGRAM_BOT_TOKEN = ""
EMBEDDED_TELEGRAM_CHAT_IDS: list[str] = []
EMBEDDED_PING_BINARY = "ping"
EMBEDDED_PING_TIMEOUT_SECONDS = 5
EMBEDDED_PING_COUNT = 1
EMBEDDED_RUN_ON_START = True
EMBEDDED_AUTO_REGISTER_CHATS = True
EMBEDDED_DATABASE_PATH = "data/monitor.db"
EMBEDDED_SERVER_CONFIG_PATH = "config/servers.json"
EMBEDDED_DAILY_REPORT_HOUR = 9
EMBEDDED_DAILY_REPORT_MINUTE = 0
EMBEDDED_WEEKLY_REPORT_WEEKDAY = 0
EMBEDDED_WEEKLY_REPORT_HOUR = 9
EMBEDDED_WEEKLY_REPORT_MINUTE = 5
EMBEDDED_FAN_PIN = 23
EMBEDDED_FAN_MIN_TEMP_C = 45.0
EMBEDDED_FAN_MAX_TEMP_C = 65.0
EMBEDDED_FAN_POLL_INTERVAL_SECONDS = 10
EMBEDDED_GUI_REFRESH_SECONDS = 5


@dataclass(slots=True)
class AppConfig:
    telegram_bot_token: str
    telegram_chat_ids: list[str]
    ping_binary: str
    ping_timeout_seconds: int
    ping_count: int
    run_on_start: bool
    auto_register_chats: bool
    database_path: Path
    server_config_path: Path
    daily_report_hour: int
    daily_report_minute: int
    weekly_report_weekday: int
    weekly_report_hour: int
    weekly_report_minute: int
    fan_settings: FanSettings
    gui_refresh_seconds: int


def _resolve_path(base_dir: Path, raw_value: str) -> Path:
    path = Path(raw_value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def load_app_config(base_dir: Path) -> AppConfig:
    return AppConfig(
        telegram_bot_token=EMBEDDED_TELEGRAM_BOT_TOKEN,
        telegram_chat_ids=EMBEDDED_TELEGRAM_CHAT_IDS.copy(),
        ping_binary=EMBEDDED_PING_BINARY,
        ping_timeout_seconds=EMBEDDED_PING_TIMEOUT_SECONDS,
        ping_count=EMBEDDED_PING_COUNT,
        run_on_start=EMBEDDED_RUN_ON_START,
        auto_register_chats=EMBEDDED_AUTO_REGISTER_CHATS,
        database_path=_resolve_path(base_dir, EMBEDDED_DATABASE_PATH),
        server_config_path=_resolve_path(base_dir, EMBEDDED_SERVER_CONFIG_PATH),
        daily_report_hour=EMBEDDED_DAILY_REPORT_HOUR,
        daily_report_minute=EMBEDDED_DAILY_REPORT_MINUTE,
        weekly_report_weekday=EMBEDDED_WEEKLY_REPORT_WEEKDAY,
        weekly_report_hour=EMBEDDED_WEEKLY_REPORT_HOUR,
        weekly_report_minute=EMBEDDED_WEEKLY_REPORT_MINUTE,
        fan_settings=FanSettings(
            pin=EMBEDDED_FAN_PIN,
            min_temp_c=EMBEDDED_FAN_MIN_TEMP_C,
            max_temp_c=EMBEDDED_FAN_MAX_TEMP_C,
            poll_interval_seconds=EMBEDDED_FAN_POLL_INTERVAL_SECONDS,
        ),
        gui_refresh_seconds=EMBEDDED_GUI_REFRESH_SECONDS,
    )


def load_servers(server_config_path: Path) -> list[ServerConfig]:
    if not server_config_path.exists():
        raise FileNotFoundError(f"Server configuration file was not found: {server_config_path}")

    raw_data = json.loads(server_config_path.read_text(encoding="utf-8"))
    if not isinstance(raw_data, list):
        raise ValueError("Server configuration must be a JSON list.")

    servers: list[ServerConfig] = []
    for item in raw_data:
        if not isinstance(item, dict):
            raise ValueError("Each server entry must be a JSON object.")

        name = str(item.get("name", "")).strip()
        address = str(item.get("address", item.get("host", ""))).strip()
        enabled = bool(item.get("enabled", True))

        if not name or not address:
            raise ValueError("Each server entry must include 'name' and 'address' fields.")

        servers.append(ServerConfig(name=name, address=address, enabled=enabled))
    return servers
