from __future__ import annotations

import platform
import re
import socket
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from math import ceil
from urllib.parse import urlparse

from monitor.models import CheckResult, ServerConfig

LINUX_LATENCY_PATTERN = re.compile(r"time[=<]([\d.]+)\s*ms", re.IGNORECASE)
WINDOWS_LATENCY_PATTERN = re.compile(r"Average = (\d+)\w+", re.IGNORECASE)
HTTP_OK_MIN = 200
HTTP_OK_MAX = 399
DEFAULT_HTTP_TIMEOUT_SECONDS = 10
SSL_DATE_FORMAT = "%b %d %H:%M:%S %Y %Z"
REQUEST_HEADERS = {
    "User-Agent": "RaspberryPiServerControlCenter/1.0",
    "Connection": "close",
}


def ping_server(
    server: ServerConfig,
    ping_binary: str,
    timeout_seconds: int,
    count: int,
    http_timeout_seconds: int = DEFAULT_HTTP_TIMEOUT_SECONDS,
) -> CheckResult:
    checked_at = datetime.now(timezone.utc)
    system_name = platform.system().lower()
    ping_target = _extract_ping_target(server.address)

    if "windows" in system_name:
        command = [ping_binary, "-n", str(count), "-w", str(timeout_seconds * 1000), ping_target]
    else:
        command = [ping_binary, "-c", str(count), "-W", str(timeout_seconds), ping_target]

    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=max(timeout_seconds + 2, 3),
        )
    except FileNotFoundError as exc:
        return _enrich_result(
            CheckResult(
                server_name=server.name,
                address=server.address,
                checked_at=checked_at,
                is_up=False,
                latency_ms=None,
                error=f"Ping command was not found: {exc}",
            ),
            server.address,
            timeout_seconds=http_timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return _enrich_result(
            CheckResult(
                server_name=server.name,
                address=server.address,
                checked_at=checked_at,
                is_up=False,
                latency_ms=None,
                error=f"Ping timed out ({timeout_seconds} sec).",
            ),
            server.address,
            timeout_seconds=http_timeout_seconds,
        )

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    output = "\n".join(part for part in [completed.stdout, completed.stderr] if part).strip()
    latency_ms = _extract_latency(output, elapsed_ms)
    is_up = completed.returncode == 0

    return _enrich_result(
        CheckResult(
            server_name=server.name,
            address=server.address,
            checked_at=checked_at,
            is_up=is_up,
            latency_ms=latency_ms,
            error=None if is_up else (output or f"Ping failed (exit code: {completed.returncode})"),
        ),
        server.address,
        timeout_seconds=http_timeout_seconds,
    )


def _extract_ping_target(address: str) -> str:
    raw = address.strip()
    if "://" not in raw:
        return raw.strip("/")
    parsed = urlparse(raw)
    return (parsed.hostname or raw).strip()


def _extract_latency(output: str, fallback_ms: float) -> float | None:
    for pattern in (LINUX_LATENCY_PATTERN, WINDOWS_LATENCY_PATTERN):
        match = pattern.search(output)
        if match:
            try:
                return round(float(match.group(1)), 2)
            except ValueError:
                return round(fallback_ms, 2)
    return round(fallback_ms, 2) if output else None


def _enrich_result(result: CheckResult, address: str, timeout_seconds: int) -> CheckResult:
    http_data = _run_http_check(address, timeout_seconds=timeout_seconds)
    ssl_data = _run_ssl_check(address, timeout_seconds=timeout_seconds, http_url=http_data["http_url"])

    result.http_url = http_data["http_url"]
    result.http_status_code = http_data["http_status_code"]
    result.http_ok = http_data["http_ok"]
    result.http_error = http_data["http_error"]
    result.ssl_expires_at = ssl_data["ssl_expires_at"]
    result.ssl_days_left = ssl_data["ssl_days_left"]
    result.ssl_error = ssl_data["ssl_error"]
    return result


def _run_http_check(address: str, timeout_seconds: int) -> dict[str, object]:
    candidates = _build_http_candidates(address)
    if not candidates:
        return {
            "http_url": None,
            "http_status_code": None,
            "http_ok": None,
            "http_error": "HTTP check skipped because the address is empty.",
        }

    last_error: str | None = None
    for url in candidates:
        try:
            request = urllib.request.Request(url, headers=REQUEST_HEADERS, method="GET")
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                status_code = int(getattr(response, "status", response.getcode()))
            return {
                "http_url": url,
                "http_status_code": status_code,
                "http_ok": HTTP_OK_MIN <= status_code <= HTTP_OK_MAX,
                "http_error": None if HTTP_OK_MIN <= status_code <= HTTP_OK_MAX else f"Unexpected HTTP status: {status_code}",
            }
        except urllib.error.HTTPError as exc:
            status_code = int(exc.code)
            return {
                "http_url": url,
                "http_status_code": status_code,
                "http_ok": HTTP_OK_MIN <= status_code <= HTTP_OK_MAX,
                "http_error": f"HTTP error: {status_code}",
            }
        except Exception as exc:
            last_error = str(exc)
            continue

    return {
        "http_url": candidates[0],
        "http_status_code": None,
        "http_ok": False,
        "http_error": last_error or "HTTP request failed.",
    }


def _build_http_candidates(address: str) -> list[str]:
    raw = address.strip().rstrip("/")
    if not raw:
        return []

    if "://" in raw:
        parsed = urlparse(raw)
        if parsed.scheme in {"http", "https"}:
            return [raw]
        return []

    return [f"https://{raw}", f"http://{raw}"]


def _run_ssl_check(address: str, timeout_seconds: int, http_url: str | None) -> dict[str, object]:
    endpoint = _extract_ssl_endpoint(address, http_url=http_url)
    if endpoint is None:
        return {
            "ssl_expires_at": None,
            "ssl_days_left": None,
            "ssl_error": None,
        }

    hostname, port = endpoint
    try:
        context = ssl.create_default_context()
        with socket.create_connection((hostname, port), timeout=timeout_seconds) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as secure_socket:
                certificate = secure_socket.getpeercert()
        not_after = certificate.get("notAfter")
        if not not_after:
            return {
                "ssl_expires_at": None,
                "ssl_days_left": None,
                "ssl_error": "SSL certificate did not include an expiry date.",
            }
        expires_at = datetime.strptime(str(not_after), SSL_DATE_FORMAT).replace(tzinfo=timezone.utc)
        remaining_seconds = (expires_at - datetime.now(timezone.utc)).total_seconds()
        if remaining_seconds >= 0:
            days_left = int(ceil(remaining_seconds / 86400))
        else:
            days_left = -int(ceil(abs(remaining_seconds) / 86400))
        return {
            "ssl_expires_at": expires_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "ssl_days_left": days_left,
            "ssl_error": None,
        }
    except Exception as exc:
        return {
            "ssl_expires_at": None,
            "ssl_days_left": None,
            "ssl_error": str(exc),
        }


def _extract_ssl_endpoint(address: str, http_url: str | None) -> tuple[str, int] | None:
    raw = address.strip()
    if not raw:
        return None

    if "://" in raw:
        parsed = urlparse(raw)
        if parsed.scheme != "https" or not parsed.hostname:
            return None
        return parsed.hostname, parsed.port or 443

    if http_url and http_url.startswith("http://"):
        return None

    if http_url and http_url.startswith("https://"):
        parsed = urlparse(http_url)
        if parsed.hostname:
            return parsed.hostname, parsed.port or 443

    host = _extract_ping_target(raw)
    if not host:
        return None
    return host, 443
