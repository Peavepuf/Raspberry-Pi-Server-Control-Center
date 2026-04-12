from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class ServerConfig:
    name: str
    address: str
    enabled: bool = True
    id: int | None = None


@dataclass(slots=True)
class CheckResult:
    server_name: str
    address: str
    checked_at: datetime
    is_up: bool
    latency_ms: float | None = None
    error: str | None = None
    http_url: str | None = None
    http_status_code: int | None = None
    http_ok: bool | None = None
    http_error: str | None = None
    ssl_expires_at: str | None = None
    ssl_days_left: int | None = None
    ssl_error: str | None = None


@dataclass(slots=True)
class UptimeStats:
    successful: int
    total: int

    @property
    def percentage(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.successful / self.total) * 100.0


@dataclass(slots=True)
class FanSettings:
    pin: int
    min_temp_c: float
    max_temp_c: float
    poll_interval_seconds: int
    active_low: bool = True
    min_speed_percent: int = 0
    max_speed_percent: int = 100
