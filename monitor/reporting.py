from __future__ import annotations

from datetime import datetime

from monitor.i18n import tr
from monitor.models import UptimeStats


def _status_emoji(is_up: bool | None) -> str:
    if is_up is None:
        return "⚪"
    return "🟢" if is_up else "🔴"


def _status_text(is_up: bool | None, lang: str) -> str:
    if is_up is None:
        return tr(lang, "unknown")
    return tr(lang, "online") if is_up else tr(lang, "offline")


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


def _http_text(server: dict[str, object], lang: str) -> str:
    http_url = server.get("http_url")
    http_status = server.get("http_status_code")
    http_ok = server.get("http_ok")
    http_error = server.get("http_error")

    if http_status is not None:
        if http_ok:
            return tr(lang, "http_ok_via", status=http_status, url=http_url)
        return tr(lang, "http_problem_via", status=http_status, url=http_url)
    if http_error:
        return tr(lang, "http_error_text", value=http_error)
    return tr(lang, "not_applicable")


def _ssl_text(server: dict[str, object], lang: str) -> str:
    days_left = server.get("ssl_days_left")
    expires_at = server.get("ssl_expires_at")
    ssl_error = server.get("ssl_error")

    if isinstance(days_left, int):
        if days_left < 0:
            return tr(lang, "ssl_expired_text", days=abs(days_left))
        if expires_at:
            return tr(lang, "ssl_days_left_text", days=days_left, expires_at=expires_at)
        return tr(lang, "ssl_days_left_no_date", days=days_left)
    if ssl_error:
        return tr(lang, "http_error_text", value=ssl_error)
    return tr(lang, "not_applicable")


def build_hourly_summary(report: dict[str, object], title: str | None = None, lang: str = "en") -> str:
    servers = list(report["servers"])
    lines = [f"{_title_emoji_from_servers(servers)} {title or tr(lang, 'hourly_report_title')}"]
    if not servers:
        lines.append(tr(lang, "no_servers_configured"))

    for server in servers:
        latency = server["latency_ms"]
        latency_text = f"{latency} ms" if latency is not None else "-"
        block = [
            f"{_status_emoji(server['is_up'])} {server['name']} ({server['address']})",
            f"  {tr(lang, 'status_line', value=_status_text(server['is_up'], lang))}",
            f"  {tr(lang, 'latency_line', value=latency_text)}",
            f"  {tr(lang, 'http_line', value=_http_text(server, lang))}",
            f"  {tr(lang, 'ssl_line', value=_ssl_text(server, lang))}",
            f"  {tr(lang, 'uptime_24h_line', value=_fmt_uptime(server['uptime_24h']))}",
            f"  {tr(lang, 'uptime_7d_line', value=_fmt_uptime(server['uptime_7d']))}",
            f"  {tr(lang, 'overall_uptime_report_line', value=_fmt_uptime(server['uptime_all']))}",
            f"  {tr(lang, 'failures_24h_line', value=server['failures_24h'])}",
        ]
        if server.get("error"):
            block.append(f"  {tr(lang, 'ping_error_line', value=server['error'])}")
        if server.get("http_error") and server.get("http_status_code") is None:
            block.append(f"  {tr(lang, 'http_detail_line', value=server['http_error'])}")
        if server.get("ssl_error") and server.get("ssl_days_left") is None:
            block.append(f"  {tr(lang, 'ssl_detail_line', value=server['ssl_error'])}")
        lines.append("\n".join(block))

    lines.append("")
    lines.append(tr(lang, "overall_24h_uptime", value=report["overall_24h"].percentage))
    lines.append(tr(lang, "overall_7d_uptime", value=report["overall_7d"].percentage))
    lines.append(tr(lang, "overall_uptime_line", value=report["overall_all"].percentage))
    lines.append(tr(lang, "total_24h_failures", value=report["failures_total_24h"]))
    lines.append(tr(lang, "total_7d_failures", value=report["failures_total_7d"]))
    lines.append(tr(lang, "generated_at", value=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    return "\n".join(lines)


def build_status_message(report: dict[str, object], lang: str = "en") -> str:
    return build_hourly_summary(report, title=tr(lang, "live_status_report"), lang=lang)


def build_uptime_message(report: dict[str, object], lang: str = "en") -> str:
    lines = [f"📈 {tr(lang, 'uptime_report')}"]
    if not report["servers"]:
        lines.append(tr(lang, "no_servers_configured"))

    for server in report["servers"]:
        lines.append(
            f"{_status_emoji(server['is_up'])} {server['name']}: 24h {_fmt_uptime(server['uptime_24h'])} | 7d {_fmt_uptime(server['uptime_7d'])} | {tr(lang, 'overall_uptime')}: {_fmt_uptime(server['uptime_all'])} | HTTP {_http_text(server, lang)}"
        )

    lines.append("")
    lines.append(tr(lang, "overall_24h_uptime", value=report["overall_24h"].percentage))
    lines.append(tr(lang, "overall_7d_uptime", value=report["overall_7d"].percentage))
    lines.append(tr(lang, "overall_uptime_line", value=report["overall_all"].percentage))
    return "\n".join(lines)


def build_servers_message(report: dict[str, object], lang: str = "en") -> str:
    lines = [f"🖥️ {tr(lang, 'current_server_states')}"]
    if not report["servers"]:
        lines.append(tr(lang, "no_servers_configured"))

    for server in report["servers"]:
        checked_at = server["last_checked_at"] or tr(lang, "not_checked_yet")
        latency = server["latency_ms"]
        latency_text = f"{latency} ms" if latency is not None else "-"
        error_suffix = f" | {tr(lang, 'ping_error_line', value=server['error'])}" if server["error"] else ""
        lines.append(
            f"{_status_emoji(server['is_up'])} {server['name']} ({server['address']}): {_status_text(server['is_up'], lang)} | {tr(lang, 'last_check')}: {checked_at} | {tr(lang, 'latency')}: {latency_text} | HTTP: {_http_text(server, lang)} | SSL: {_ssl_text(server, lang)}{error_suffix}"
        )
    return "\n".join(lines)


def build_daily_summary(report: dict[str, object], lang: str = "en") -> str:
    lines = [f"🗓️ {tr(lang, 'daily_summary_title')}"]
    if not report["servers"]:
        lines.append(tr(lang, "no_servers_configured"))

    for server in report["servers"]:
        lines.append(
            f"{_status_emoji(server['is_up'])} {server['name']}: {_fmt_uptime(server['uptime'])} | {tr(lang, 'failures_24h_line', value=server['failures'])} | HTTP: {_http_text(server, lang)} | SSL: {_ssl_text(server, lang)}"
        )

    lines.append("")
    lines.append(tr(lang, "overall_daily_uptime", value=_fmt_uptime(report["overall"])))
    lines.append(tr(lang, "daily_total_failures", value=report["total_failures"]))
    lines.append(tr(lang, "generated_at", value=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    return "\n".join(lines)


def build_weekly_summary(report: dict[str, object], lang: str = "en") -> str:
    lines = [f"🗓️ {tr(lang, 'weekly_summary_title')}"]
    if not report["servers"]:
        lines.append(tr(lang, "no_servers_configured"))

    for server in report["servers"]:
        lines.append(
            f"{_status_emoji(server['is_up'])} {server['name']}: {_fmt_uptime(server['uptime'])} | {tr(lang, 'failures_24h_line', value=server['failures'])} | HTTP: {_http_text(server, lang)} | SSL: {_ssl_text(server, lang)}"
        )

    lines.append("")
    lines.append(tr(lang, "overall_weekly_uptime", value=_fmt_uptime(report["overall"])))
    lines.append(tr(lang, "weekly_total_failures", value=report["total_failures"]))
    lines.append(tr(lang, "generated_at", value=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    return "\n".join(lines)


def build_state_change_message(changes: list[dict[str, object]], lang: str = "en") -> str:
    if not changes:
        return ""

    any_down = any(change["is_up"] is False for change in changes)
    title = tr(lang, "status_change_alert") if any_down else tr(lang, "status_change_notification")
    lines = [f"{'🚨' if any_down else '✅'} {title}"]

    for change in changes:
        if change["is_up"]:
            lines.append(f"🟢 {tr(lang, 'is_reachable_again', name=change['name'], address=change['address'])}")
        else:
            lines.append(f"🔴 {tr(lang, 'is_not_reachable', name=change['name'], address=change['address'])}")
            if change.get("error"):
                lines.append(f"  {tr(lang, 'http_error_text', value=change['error'])}")

    lines.append(tr(lang, "generated_at", value=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    return "\n".join(lines)


def build_ssl_warning_message(warnings: list[dict[str, object]], lang: str = "en") -> str:
    if not warnings:
        return ""

    lines = [f"⚠️ {tr(lang, 'ssl_expiry_warning')}"]
    for warning in warnings:
        if warning["expired"]:
            lines.append(
                f"🔴 {tr(lang, 'ssl_expired_message', name=warning['name'], address=warning['address'], expires_at=warning['expires_at'])}"
            )
        else:
            lines.append(
                f"🟠 {tr(lang, 'ssl_expiring_message', name=warning['name'], address=warning['address'], days_left=warning['days_left'], expires_at=warning['expires_at'])}"
            )
    lines.append(tr(lang, "generated_at", value=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
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
