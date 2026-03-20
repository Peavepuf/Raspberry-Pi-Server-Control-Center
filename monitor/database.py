from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from monitor.models import CheckResult, FanSettings, ServerConfig, UptimeStats


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def datetime_to_str(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._initialize()

    def _initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS servers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    host TEXT NOT NULL UNIQUE,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS checks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id INTEGER NOT NULL,
                    checked_at TEXT NOT NULL,
                    is_up INTEGER NOT NULL,
                    latency_ms REAL,
                    error TEXT,
                    http_url TEXT,
                    http_status_code INTEGER,
                    http_ok INTEGER,
                    http_error TEXT,
                    ssl_expires_at TEXT,
                    ssl_days_left INTEGER,
                    ssl_error TEXT,
                    FOREIGN KEY(server_id) REFERENCES servers(id)
                );

                CREATE TABLE IF NOT EXISTS app_state (
                    state_key TEXT PRIMARY KEY,
                    state_value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS telegram_chats (
                    chat_id TEXT PRIMARY KEY,
                    title TEXT,
                    discovered_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS fan_settings (
                    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                    pin INTEGER NOT NULL,
                    min_temp_c REAL NOT NULL,
                    max_temp_c REAL NOT NULL,
                    poll_interval_seconds INTEGER NOT NULL,
                    min_speed_percent INTEGER NOT NULL,
                    max_speed_percent INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            self._ensure_server_timestamps()
            self._ensure_check_columns()

    def _ensure_server_timestamps(self) -> None:
        columns = {row["name"] for row in self._connection.execute("PRAGMA table_info(servers)").fetchall()}
        now = datetime_to_str(utc_now())
        if "updated_at" not in columns:
            self._connection.execute("ALTER TABLE servers ADD COLUMN updated_at TEXT")
            self._connection.execute("UPDATE servers SET updated_at = ?", (now,))
        if "created_at" in columns:
            self._connection.execute("UPDATE servers SET created_at = COALESCE(created_at, ?)", (now,))
        self._connection.execute("UPDATE servers SET updated_at = COALESCE(updated_at, ?)", (now,))

    def _ensure_check_columns(self) -> None:
        columns = {row["name"] for row in self._connection.execute("PRAGMA table_info(checks)").fetchall()}
        required_columns = {
            "http_url": "TEXT",
            "http_status_code": "INTEGER",
            "http_ok": "INTEGER",
            "http_error": "TEXT",
            "ssl_expires_at": "TEXT",
            "ssl_days_left": "INTEGER",
            "ssl_error": "TEXT",
        }
        for column_name, column_type in required_columns.items():
            if column_name not in columns:
                self._connection.execute(f"ALTER TABLE checks ADD COLUMN {column_name} {column_type}")

    def seed_servers_if_empty(self, servers: list[ServerConfig]) -> None:
        with self._lock:
            row = self._connection.execute("SELECT COUNT(*) AS total FROM servers").fetchone()
            total = int(row["total"] or 0)
        if total == 0 and servers:
            for server in servers:
                self.save_server(name=server.name, address=server.address, enabled=server.enabled)

    def ensure_fan_settings(self, default_settings: FanSettings) -> None:
        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) AS total FROM fan_settings WHERE singleton_id = 1"
            ).fetchone()
            total = int(row["total"] or 0)
        if total == 0:
            self.save_fan_settings(default_settings)

    def ensure_telegram_settings(self, token: str, chat_ids: list[str]) -> None:
        with self._lock, self._connection:
            token_row = self._connection.execute(
                "SELECT state_value FROM app_state WHERE state_key = 'telegram_bot_token'"
            ).fetchone()
            chat_row = self._connection.execute(
                "SELECT state_value FROM app_state WHERE state_key = 'telegram_chat_ids'"
            ).fetchone()

            if token_row is None:
                self._connection.execute(
                    """
                    INSERT INTO app_state (state_key, state_value)
                    VALUES ('telegram_bot_token', ?)
                    """,
                    (token.strip(),),
                )

            if chat_row is None:
                self._connection.execute(
                    """
                    INSERT INTO app_state (state_key, state_value)
                    VALUES ('telegram_chat_ids', ?)
                    """,
                    (",".join(chat_ids),),
                )

    def list_servers(self, enabled_only: bool = False) -> list[ServerConfig]:
        query = "SELECT id, name, host, enabled FROM servers"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY name ASC"
        with self._lock:
            rows = self._connection.execute(query).fetchall()
        return [
            ServerConfig(
                id=int(row["id"]),
                name=str(row["name"]),
                address=str(row["host"]),
                enabled=bool(row["enabled"]),
            )
            for row in rows
        ]

    def save_server(self, *, name: str, address: str, enabled: bool = True, server_id: int | None = None) -> int:
        timestamp = datetime_to_str(utc_now())
        with self._lock, self._connection:
            if server_id is None:
                cursor = self._connection.execute(
                    """
                    INSERT INTO servers (name, host, enabled, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (name, address, int(enabled), timestamp, timestamp),
                )
                return int(cursor.lastrowid)

            self._connection.execute(
                """
                UPDATE servers
                SET name = ?, host = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (name, address, int(enabled), timestamp, server_id),
            )
            return server_id

    def delete_server(self, server_id: int) -> None:
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM checks WHERE server_id = ?", (server_id,))
            self._connection.execute("DELETE FROM servers WHERE id = ?", (server_id,))

    def save_fan_settings(self, settings: FanSettings) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO fan_settings (
                    singleton_id, pin, min_temp_c, max_temp_c, poll_interval_seconds,
                    min_speed_percent, max_speed_percent, updated_at
                )
                VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    pin = excluded.pin,
                    min_temp_c = excluded.min_temp_c,
                    max_temp_c = excluded.max_temp_c,
                    poll_interval_seconds = excluded.poll_interval_seconds,
                    min_speed_percent = excluded.min_speed_percent,
                    max_speed_percent = excluded.max_speed_percent,
                    updated_at = excluded.updated_at
                """,
                (
                    settings.pin,
                    settings.min_temp_c,
                    settings.max_temp_c,
                    settings.poll_interval_seconds,
                    settings.min_speed_percent,
                    settings.max_speed_percent,
                    datetime_to_str(utc_now()),
                ),
            )

    def get_fan_settings(self) -> FanSettings:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT pin, min_temp_c, max_temp_c, poll_interval_seconds, min_speed_percent, max_speed_percent
                FROM fan_settings
                WHERE singleton_id = 1
                """
            ).fetchone()
        if row is None:
            raise ValueError("Fan settings were not found.")
        return FanSettings(
            pin=int(row["pin"]),
            min_temp_c=float(row["min_temp_c"]),
            max_temp_c=float(row["max_temp_c"]),
            poll_interval_seconds=int(row["poll_interval_seconds"]),
            min_speed_percent=int(row["min_speed_percent"]),
            max_speed_percent=int(row["max_speed_percent"]),
        )

    def add_check_result(self, result: CheckResult) -> None:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT id FROM servers WHERE name = ?",
                (result.server_name,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Server is not registered: {result.server_name}")

            self._connection.execute(
                """
                INSERT INTO checks (
                    server_id, checked_at, is_up, latency_ms, error,
                    http_url, http_status_code, http_ok, http_error,
                    ssl_expires_at, ssl_days_left, ssl_error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    datetime_to_str(result.checked_at),
                    int(result.is_up),
                    result.latency_ms,
                    result.error,
                    result.http_url,
                    result.http_status_code,
                    None if result.http_ok is None else int(result.http_ok),
                    result.http_error,
                    result.ssl_expires_at,
                    result.ssl_days_left,
                    result.ssl_error,
                ),
            )

    def set_state(self, key: str, value: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO app_state (state_key, state_value)
                VALUES (?, ?)
                ON CONFLICT(state_key) DO UPDATE SET
                    state_value=excluded.state_value
                """,
                (key, value),
            )

    def get_state(self, key: str, default: str | None = None) -> str | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT state_value FROM app_state WHERE state_key = ?",
                (key,),
            ).fetchone()
        return default if row is None else str(row["state_value"])

    def get_telegram_settings(self) -> dict[str, object]:
        token = self.get_state("telegram_bot_token", "") or ""
        raw_chat_ids = self.get_state("telegram_chat_ids", "") or ""
        chat_ids = [item.strip() for item in raw_chat_ids.split(",") if item.strip()]
        return {
            "token": token,
            "chat_ids": chat_ids,
            "chat_ids_raw": ",".join(chat_ids),
        }

    def save_telegram_settings(self, token: str, chat_ids: list[str]) -> None:
        clean_token = token.strip()
        clean_chat_ids = [item.strip() for item in chat_ids if item.strip()]
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO app_state (state_key, state_value)
                VALUES ('telegram_bot_token', ?)
                ON CONFLICT(state_key) DO UPDATE SET state_value = excluded.state_value
                """,
                (clean_token,),
            )
            self._connection.execute(
                """
                INSERT INTO app_state (state_key, state_value)
                VALUES ('telegram_chat_ids', ?)
                ON CONFLICT(state_key) DO UPDATE SET state_value = excluded.state_value
                """,
                (",".join(clean_chat_ids),),
            )

    def add_chat(self, chat_id: str, title: str | None = None) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO telegram_chats (chat_id, title, discovered_at, is_active)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(chat_id) DO UPDATE SET
                    title=excluded.title,
                    is_active=1
                """,
                (chat_id, title, datetime_to_str(utc_now())),
            )

    def get_active_chat_ids(self) -> list[str]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT chat_id FROM telegram_chats WHERE is_active = 1 ORDER BY discovered_at ASC"
            ).fetchall()
        return [str(row["chat_id"]) for row in rows]

    def get_discovered_chats(self) -> list[dict[str, str]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT chat_id, COALESCE(title, '') AS title, discovered_at FROM telegram_chats ORDER BY discovered_at ASC"
            ).fetchall()
        return [
            {
                "chat_id": str(row["chat_id"]),
                "title": str(row["title"]),
                "discovered_at": str(row["discovered_at"]),
            }
            for row in rows
        ]

    def get_latest_server_rows(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(
                """
                SELECT
                    s.id,
                    s.name,
                    s.host,
                    s.enabled,
                    c.checked_at,
                    c.is_up,
                    c.latency_ms,
                    c.error,
                    c.http_url,
                    c.http_status_code,
                    c.http_ok,
                    c.http_error,
                    c.ssl_expires_at,
                    c.ssl_days_left,
                    c.ssl_error
                FROM servers s
                LEFT JOIN checks c
                    ON c.id = (
                        SELECT id
                        FROM checks
                        WHERE server_id = s.id
                        ORDER BY checked_at DESC
                        LIMIT 1
                    )
                WHERE s.enabled = 1
                ORDER BY s.name ASC
                """
            ).fetchall()

    def get_latest_status_map(self) -> dict[str, bool | None]:
        status_map: dict[str, bool | None] = {}
        for row in self.get_latest_server_rows():
            status_map[str(row["name"])] = None if row["is_up"] is None else bool(row["is_up"])
        return status_map

    def _aggregate_stats(self, since: datetime | None = None) -> tuple[dict[str, UptimeStats], UptimeStats]:
        condition = ""
        params: list[str] = []
        if since is not None:
            condition = " AND c.checked_at >= ?"
            params.append(datetime_to_str(since))

        query = f"""
            SELECT
                s.name AS server_name,
                SUM(CASE WHEN c.is_up = 1 THEN 1 ELSE 0 END) AS successful,
                COUNT(c.id) AS total
            FROM servers s
            LEFT JOIN checks c ON c.server_id = s.id{condition}
            WHERE s.enabled = 1
            GROUP BY s.id, s.name
            ORDER BY s.name ASC
        """
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()

        per_server: dict[str, UptimeStats] = {}
        successful_total = 0
        grand_total = 0
        for row in rows:
            successful = int(row["successful"] or 0)
            total = int(row["total"] or 0)
            per_server[str(row["server_name"])] = UptimeStats(successful=successful, total=total)
            successful_total += successful
            grand_total += total
        return per_server, UptimeStats(successful=successful_total, total=grand_total)

    def _aggregate_failures(self, since: datetime | None = None) -> tuple[dict[str, int], int]:
        condition = ""
        params: list[str] = []
        if since is not None:
            condition = " AND c.checked_at >= ?"
            params.append(datetime_to_str(since))

        query = f"""
            SELECT
                s.name AS server_name,
                SUM(CASE WHEN c.is_up = 0 THEN 1 ELSE 0 END) AS failures
            FROM servers s
            LEFT JOIN checks c ON c.server_id = s.id{condition}
            WHERE s.enabled = 1
            GROUP BY s.id, s.name
            ORDER BY s.name ASC
        """
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()

        per_server: dict[str, int] = {}
        total_failures = 0
        for row in rows:
            failures = int(row["failures"] or 0)
            per_server[str(row["server_name"])] = failures
            total_failures += failures
        return per_server, total_failures

    def get_period_report(self, hours: int) -> dict[str, object]:
        since = utc_now() - timedelta(hours=hours)
        latest_rows = self.get_latest_server_rows()
        stats, overall = self._aggregate_stats(since=since)
        failures, total_failures = self._aggregate_failures(since=since)

        servers: list[dict[str, object]] = []
        for row in latest_rows:
            name = str(row["name"])
            servers.append(
                {
                    "id": int(row["id"]),
                    "name": name,
                    "address": str(row["host"]),
                    "enabled": bool(row["enabled"]),
                    "last_checked_at": row["checked_at"],
                    "is_up": None if row["is_up"] is None else bool(row["is_up"]),
                    "latency_ms": row["latency_ms"],
                    "error": row["error"],
                    "http_url": row["http_url"],
                    "http_status_code": row["http_status_code"],
                    "http_ok": None if row["http_ok"] is None else bool(row["http_ok"]),
                    "http_error": row["http_error"],
                    "ssl_expires_at": row["ssl_expires_at"],
                    "ssl_days_left": row["ssl_days_left"],
                    "ssl_error": row["ssl_error"],
                    "uptime": stats.get(name, UptimeStats(0, 0)),
                    "failures": failures.get(name, 0),
                }
            )

        return {
            "window_hours": hours,
            "window_days": round(hours / 24, 2),
            "servers": servers,
            "overall": overall,
            "total_failures": total_failures,
        }

    def get_uptime_report(self) -> dict[str, object]:
        latest_rows = self.get_latest_server_rows()
        last_24h = utc_now() - timedelta(hours=24)
        last_7d = utc_now() - timedelta(days=7)

        last24_stats, overall24 = self._aggregate_stats(since=last_24h)
        last7d_stats, overall7d = self._aggregate_stats(since=last_7d)
        all_time_stats, overall_all = self._aggregate_stats()

        failures24, failures_total_24 = self._aggregate_failures(since=last_24h)
        failures7d, failures_total_7 = self._aggregate_failures(since=last_7d)

        servers: list[dict[str, object]] = []
        for row in latest_rows:
            name = str(row["name"])
            servers.append(
                {
                    "id": int(row["id"]),
                    "name": name,
                    "address": str(row["host"]),
                    "enabled": bool(row["enabled"]),
                    "last_checked_at": row["checked_at"],
                    "is_up": None if row["is_up"] is None else bool(row["is_up"]),
                    "latency_ms": row["latency_ms"],
                    "error": row["error"],
                    "http_url": row["http_url"],
                    "http_status_code": row["http_status_code"],
                    "http_ok": None if row["http_ok"] is None else bool(row["http_ok"]),
                    "http_error": row["http_error"],
                    "ssl_expires_at": row["ssl_expires_at"],
                    "ssl_days_left": row["ssl_days_left"],
                    "ssl_error": row["ssl_error"],
                    "uptime_24h": last24_stats.get(name, UptimeStats(0, 0)),
                    "uptime_7d": last7d_stats.get(name, UptimeStats(0, 0)),
                    "uptime_all": all_time_stats.get(name, UptimeStats(0, 0)),
                    "failures_24h": failures24.get(name, 0),
                    "failures_7d": failures7d.get(name, 0),
                }
            )

        return {
            "servers": servers,
            "overall_24h": overall24,
            "overall_7d": overall7d,
            "overall_all": overall_all,
            "failures_total_24h": failures_total_24,
            "failures_total_7d": failures_total_7,
        }

    def close(self) -> None:
        with self._lock:
            self._connection.close()
