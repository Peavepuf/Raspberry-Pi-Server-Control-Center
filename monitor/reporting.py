from __future__ import annotations

from datetime import datetime

from monitor.models import UptimeStats


def _status_emoji(is_up: bool | None) -> str:
    if is_up is None:
        return "⚪"
    return "🟢" if is_up else "🔴"


def _status_text(is_up: bool | None) -> str:
    if is_up is None:
        return "Unknown"
    return "Online" if is_up else "Offline"


def _fmt_uptime(stats: UptimeStats) -> str:
    return f"{stats.percentage:.1f}% ({stats.successful}/{stats.total})"


def _server_has_issue(server: dict[str, object]) -> bool:
    if server["is_up"] is False:
        return True
    if server.get("http_ok") is False:
        return True
    ssl_days_left = server.get("ssl_days_left")
    return isinstance(ssl_days_left, int) and ssl_days_left < 0


def _title_emoji_from_servers(servers: list[dict[str, object]]) -> str:
    return "🚨" if any(_server_has_issue(server) for server in servers) else "🛰️"


def _http_text(server: dict[str, object]) -> str:
    http_url = server.get("http_url")
    http_status = server.get("http_status_code")
    http_ok = server.get("http_ok")
    http_error = server.get("http_error")

    if http_status is not None:
        label = "OK" if http_ok else "Problem"
        return f"{http_status} ({label}) via {http_url}"
    if http_error:
        return f"Error: {http_error}"
    return "Not applicable"


def _ssl_text(server: dict[str, object]) -> str:
    days_left = server.get("ssl_days_left")
    expires_at = server.get("ssl_expires_at")
    ssl_error = server.get("ssl_error")

    if isinstance(days_left, int):
        if days_left < 0:
            return f"Expired ({abs(days_left)} day(s) ago)"
        if expires_at:
            return f"{days_left} day(s) left | Expires: {expires_at}"
        return f"{days_left} day(s) left"
    if ssl_error:
        return f"Error: {ssl_error}"
    return "Not applicable"


def build_hourly_summary(report: dict[str, object], title: str = "Hourly server report") -> str:
    servers = list(report["servers"])
    lines = [f"{_title_emoji_from_servers(servers)} {title}"]
    if not servers:
        lines.append("No servers have been configured yet.")

    for server in servers:
        latency = server["latency_ms"]
        latency_text = f"{latency} ms" if latency is not None else "-"
        block = [
            f"{_status_emoji(server['is_up'])} {server['name']} ({server['address']})",
            f"  Status: {_status_text(server['is_up'])}",
            f"  Latency: {latency_text}",
            f"  HTTP: {_http_text(server)}",
            f"  SSL: {_ssl_text(server)}",
            f"  24h uptime: {_fmt_uptime(server['uptime_24h'])}",
            f"  7d uptime: {_fmt_uptime(server['uptime_7d'])}",
            f"  Overall uptime: {_fmt_uptime(server['uptime_all'])}",
            f"  24h failures: {server['failures_24h']}",
        ]
        if server.get("error"):
            block.append(f"  Ping error: {server['error']}")
        if server.get("http_error") and server.get("http_status_code") is None:
            block.append(f"  HTTP detail: {server['http_error']}")
        if server.get("ssl_error") and server.get("ssl_days_left") is None:
            block.append(f"  SSL detail: {server['ssl_error']}")
        lines.append("\n".join(block))

    lines.append("")
    lines.append(f"Overall 24h uptime: {_fmt_uptime(report['overall_24h'])}")
    lines.append(f"Overall 7d uptime: {_fmt_uptime(report['overall_7d'])}")
    lines.append(f"Overall uptime: {_fmt_uptime(report['overall_all'])}")
    lines.append(f"Total 24h failures: {report['failures_total_24h']}")
    lines.append(f"Total 7d failures: {report['failures_total_7d']}")
    lines.append(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return "\n".join(lines)


def build_status_message(report: dict[str, object]) -> str:
    return build_hourly_summary(report, title="Live status report")


def build_uptime_message(report: dict[str, object]) -> str:
    lines = ["📈 Uptime report"]
    if not report["servers"]:
        lines.append("No servers have been configured yet.")

    for server in report["servers"]:
        lines.append(
            f"{_status_emoji(server['is_up'])} {server['name']}: 24h {_fmt_uptime(server['uptime_24h'])} | 7d {_fmt_uptime(server['uptime_7d'])} | Overall {_fmt_uptime(server['uptime_all'])} | HTTP {_http_text(server)}"
        )

    lines.append("")
    lines.append(f"Overall 24h uptime: {_fmt_uptime(report['overall_24h'])}")
    lines.append(f"Overall 7d uptime: {_fmt_uptime(report['overall_7d'])}")
    lines.append(f"Overall uptime: {_fmt_uptime(report['overall_all'])}")
    return "\n".join(lines)


def build_servers_message(report: dict[str, object]) -> str:
    lines = ["🖥️ Current server states"]
    if not report["servers"]:
        lines.append("No servers have been configured yet.")

    for server in report["servers"]:
        checked_at = server["last_checked_at"] or "Not checked yet"
        latency = server["latency_ms"]
        latency_text = f"{latency} ms" if latency is not None else "-"
        error_suffix = f" | Ping error: {server['error']}" if server["error"] else ""
        lines.append(
            f"{_status_emoji(server['is_up'])} {server['name']} ({server['address']}): {_status_text(server['is_up'])} | Last check: {checked_at} | Latency: {latency_text} | HTTP: {_http_text(server)} | SSL: {_ssl_text(server)}{error_suffix}"
        )
    return "\n".join(lines)


def build_daily_summary(report: dict[str, object]) -> str:
    lines = ["🗓️ Daily summary (last 24 hours)"]
    if not report["servers"]:
        lines.append("No servers have been configured yet.")

    for server in report["servers"]:
        lines.append(
            f"{_status_emoji(server['is_up'])} {server['name']}: uptime {_fmt_uptime(server['uptime'])} | Failures: {server['failures']} | HTTP: {_http_text(server)} | SSL: {_ssl_text(server)}"
        )

    lines.append("")
    lines.append(f"Overall daily uptime: {_fmt_uptime(report['overall'])}")
    lines.append(f"Daily total failures: {report['total_failures']}")
    lines.append(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return "\n".join(lines)


def build_weekly_summary(report: dict[str, object]) -> str:
    lines = ["🗓️ Weekly summary (last 7 days)"]
    if not report["servers"]:
        lines.append("No servers have been configured yet.")

    for server in report["servers"]:
        lines.append(
            f"{_status_emoji(server['is_up'])} {server['name']}: uptime {_fmt_uptime(server['uptime'])} | Failures: {server['failures']} | HTTP: {_http_text(server)} | SSL: {_ssl_text(server)}"
        )

    lines.append("")
    lines.append(f"Overall weekly uptime: {_fmt_uptime(report['overall'])}")
    lines.append(f"Weekly total failures: {report['total_failures']}")
    lines.append(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return "\n".join(lines)


def build_state_change_message(changes: list[dict[str, object]]) -> str:
    if not changes:
        return ""

    any_down = any(change["is_up"] is False for change in changes)
    title = "🚨 Status change alert" if any_down else "✅ Status change notification"
    lines = [title]

    for change in changes:
        if change["is_up"]:
            lines.append(f"🟢 {change['name']} ({change['address']}) is reachable again.")
        else:
            lines.append(f"🔴 {change['name']} ({change['address']}) is not reachable.")
            if change.get("error"):
                lines.append(f"  Error: {change['error']}")

    lines.append(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return "\n".join(lines)


def build_ssl_warning_message(warnings: list[dict[str, object]]) -> str:
    if not warnings:
        return ""

    lines = ["⚠️ SSL expiry warning"]
    for warning in warnings:
        if warning["expired"]:
            lines.append(
                f"🔴 {warning['name']} ({warning['address']}): SSL certificate has expired. Expires/expired at: {warning['expires_at']}"
            )
        else:
            lines.append(
                f"🟠 {warning['name']} ({warning['address']}): SSL certificate expires in {warning['days_left']} day(s). Expiry date: {warning['expires_at']}"
            )
    lines.append(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return "\n".join(lines)


def chunk_message(message: str, limit: int = 3900) -> list[str]:
    if len(message) <= limit:
        return [message]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in message.splitlines():
        if current_len + len(line) + 1 > limit and current:
            chunks.append("\n".join(current))
            current = [line]
            current_len = len(line) + 1
        else:
            current.append(line)
            current_len += len(line) + 1

    if current:
        chunks.append("\n".join(current))
    return chunks
