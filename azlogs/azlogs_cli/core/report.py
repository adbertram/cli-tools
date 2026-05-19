"""Generate report.html with aggregate metrics from parsed log entries."""

from __future__ import annotations

import html
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from typing import Optional

from ..models import Entity, LogLevel
from .types import InternalLogEntry, Session


def _pct(n: int, total: int) -> str:
    return f"{n / total * 100:.1f}%" if total else "0%"


def _fmt_duration(td: timedelta) -> str:
    total_secs = int(td.total_seconds())
    days, rem = divmod(total_secs, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    # Include seconds for sub-hour durations to show precise session lengths
    if not days and not hours:
        parts.append(f"{secs}s")
    return " ".join(parts)


def _level_class(level: str) -> str:
    return {
        "ERROR": "error", "WARNING": "warning",
        "DEBUG": "debug", "UNKNOWN": "unknown",
    }.get(level, "info")


def _build_summary(entries: list[InternalLogEntry]) -> dict:
    if not entries:
        return {"total": 0}
    timestamps = [e.timestamp for e in entries]
    return {
        "total": len(entries),
        "earliest": min(timestamps),
        "latest": max(timestamps),
        "span": max(timestamps) - min(timestamps),
        "source_files": len({e.source_file for e in entries}),
    }


def _count_by(entries: list[InternalLogEntry], key: str) -> list[tuple[str, int]]:
    counts = Counter(getattr(e, key) if not isinstance(getattr(e, key), Entity | LogLevel) else getattr(e, key).value for e in entries)
    return sorted(counts.items(), key=lambda x: -x[1])


def _level_by_service(entries: list[InternalLogEntry]) -> dict[str, Counter]:
    """Return {service: Counter({level_value: count})}."""
    result: dict[str, Counter] = defaultdict(Counter)
    for e in entries:
        result[e.service][e.level.value] += 1
    return dict(result)


def _entity_time_ranges(entries: list[InternalLogEntry]) -> list[tuple[str, datetime, datetime, timedelta]]:
    """Return [(entity, earliest, latest, span)] sorted by span desc."""
    by_entity: dict[str, list[datetime]] = defaultdict(list)
    for e in entries:
        by_entity[e.entity.value].append(e.timestamp)
    rows = []
    for entity, timestamps in by_entity.items():
        lo, hi = min(timestamps), max(timestamps)
        rows.append((entity, lo, hi, hi - lo))
    return sorted(rows, key=lambda x: -x[3].total_seconds())


def _hourly_histogram(entries: list[InternalLogEntry]) -> list[tuple[str, int]]:
    """Return [(hour_label, count)] for each hour with entries."""
    buckets: Counter = Counter()
    for e in entries:
        buckets[e.timestamp.strftime("%Y-%m-%d %H:00")] += 1
    return sorted(buckets.items())


def _errors_detail(entries: list[InternalLogEntry], limit: int = 50) -> list[InternalLogEntry]:
    """Return the most recent ERROR entries."""
    errors = [e for e in entries if e.level is LogLevel.ERROR]
    return sorted(errors, key=lambda e: e.timestamp, reverse=True)[:limit]


def _group_issues(entries: list[InternalLogEntry]) -> list[dict]:
    """Group ERROR and WARNING entries by deduplicated message signature.

    Returns list of dicts sorted by (severity, count desc, latest desc):
      {level, service, entity, signature, full_message, count, first, last, occurrences}
    """
    groups: dict[tuple[str, str, str, str], dict] = {}

    for e in entries:
        if e.level not in (LogLevel.ERROR, LogLevel.WARNING):
            continue
        # Signature = first line of message (deduplicates stack traces)
        first_line = e.message.split("\n")[0].strip()
        key = (e.level.value, e.service, e.entity.value, first_line)

        if key not in groups:
            groups[key] = {
                "level": e.level.value,
                "service": e.service,
                "entity": e.entity.value,
                "signature": first_line,
                "full_message": e.message,
                "count": 0,
                "first": e.timestamp,
                "last": e.timestamp,
                "occurrences": [],
            }
        g = groups[key]
        g["count"] += 1
        if e.timestamp < g["first"]:
            g["first"] = e.timestamp
        if e.timestamp > g["last"]:
            g["last"] = e.timestamp
            g["full_message"] = e.message  # keep most recent full trace
        g["occurrences"].append(e)

    return sorted(
        groups.values(),
        key=lambda g: g["last"],
        reverse=True,
    )


def _render_table(headers: list[str], rows: list[list[str]], classes: str = "") -> str:
    cls = f' class="{classes}"' if classes else ""
    lines = [f"<table{cls}>", "<thead><tr>"]
    for h in headers:
        lines.append(f"<th>{html.escape(h)}</th>")
    lines.append("</tr></thead><tbody>")
    for row in rows:
        lines.append("<tr>")
        for cell in row:
            lines.append(f"<td>{cell}</td>")
        lines.append("</tr>")
    lines.append("</tbody></table>")
    return "\n".join(lines)


def _bar(value: int, max_value: int, color: str = "#4a90d9") -> str:
    pct = value / max_value * 100 if max_value else 0
    return (
        f'<div class="bar-container">'
        f'<div class="bar" style="width:{pct:.1f}%;background:{color}"></div>'
        f'</div>'
    )


_CSS = """\
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       background: #f5f5f5; color: #333; padding: 24px; max-width: 1200px; margin: 0 auto; }
h1 { font-size: 1.6em; margin-bottom: 4px; }
h2 { font-size: 1.15em; margin: 28px 0 10px 0; color: #555; border-bottom: 1px solid #ddd; padding-bottom: 4px; }
.subtitle { color: #888; font-size: 0.9em; margin-bottom: 20px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 20px; }
.card { background: #fff; border-radius: 8px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.card .label { font-size: 0.8em; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }
.card .value { font-size: 1.6em; font-weight: 600; margin-top: 4px; }
table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px;
        overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 16px; }
th { background: #f8f9fa; text-align: left; padding: 8px 12px; font-size: 0.8em;
     text-transform: uppercase; color: #666; letter-spacing: 0.5px; }
td { padding: 6px 12px; border-top: 1px solid #eee; font-size: 0.9em; }
tr:hover { background: #f8f9fb; }
.mono { font-family: "SF Mono", Menlo, monospace; font-size: 0.85em; }
.bar-container { width: 100%; background: #eee; border-radius: 3px; height: 14px; }
.bar { height: 100%; border-radius: 3px; min-width: 2px; }
.badge { display: inline-block; padding: 1px 7px; border-radius: 4px; font-size: 0.8em; font-weight: 500; }
.badge.error { background: #fde8e8; color: #c0392b; }
.badge.warning { background: #fef3cd; color: #856404; }
.badge.info { background: #d1ecf1; color: #0c5460; }
.badge.debug { background: #e8e8e8; color: #666; }
.badge.unknown { background: #f0f0f0; color: #999; }
.msg { max-width: 600px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.section { margin-bottom: 32px; }
.issue-card { background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.08);
              margin-bottom: 10px; overflow: hidden; }
.issue-card.error-card { border-left: 4px solid #e74c3c; }
.issue-card.warning-card { border-left: 4px solid #f39c12; }
.issue-header { padding: 12px 16px; cursor: pointer; display: flex; align-items: center; gap: 10px; }
.issue-header:hover { background: #fafafa; }
.issue-header .arrow { transition: transform 0.2s; font-size: 0.7em; color: #999; }
.issue-card[open] .arrow { transform: rotate(90deg); }
.issue-meta { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; flex: 1; }
.issue-sig { font-family: "SF Mono", Menlo, monospace; font-size: 0.85em; color: #333;
             overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 650px; }
.issue-count { background: #eee; border-radius: 10px; padding: 1px 8px; font-size: 0.8em;
               font-weight: 600; white-space: nowrap; }
.issue-card.error-card .issue-count { background: #fde8e8; color: #c0392b; }
.issue-card.warning-card .issue-count { background: #fef3cd; color: #856404; }
.issue-body { padding: 0 16px 14px 16px; border-top: 1px solid #f0f0f0; }
.issue-body pre { background: #f8f8f8; border-radius: 6px; padding: 10px 12px; font-size: 0.82em;
                  font-family: "SF Mono", Menlo, monospace; overflow-x: auto; white-space: pre-wrap;
                  word-break: break-word; margin: 8px 0; color: #444; max-height: 300px; overflow-y: auto; }
.issue-body .occ-table { margin-top: 8px; font-size: 0.85em; }
.issue-body .occ-table td { padding: 3px 10px; }
.issue-tags { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 2px; }
.issue-tags code { font-size: 0.8em; background: #f0f0f0; padding: 1px 6px; border-radius: 3px; }
.no-issues { background: #d4edda; color: #155724; border-radius: 8px; padding: 16px;
             font-weight: 500; margin-bottom: 20px; }
.issues-wrapper { margin-bottom: 32px; }
.issues-wrapper > summary { cursor: pointer; list-style: none; }
.issues-wrapper > summary::-webkit-details-marker { display: none; }
.issues-wrapper > summary::marker { display: none; content: ""; }
.issues-toggle { display: flex; align-items: center; gap: 8px; padding: 10px 0; }
.issues-toggle .arrow { transition: transform 0.2s; font-size: 0.7em; color: #555; }
.issues-wrapper[open] > summary .arrow { transform: rotate(90deg); }
.issues-toggle h2 { margin: 0; border: none; padding: 0; }
.issues-content { margin-top: 10px; }
.session-card { background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.08);
                margin-bottom: 10px; overflow: hidden; border-left: 4px solid #3498db; }
.session-card.open-session { border-left-color: #2ecc71; }
.session-header { padding: 12px 16px; cursor: pointer; display: flex; align-items: center; gap: 10px; }
.session-header:hover { background: #fafafa; }
.session-meta { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; flex: 1; font-size: 0.9em; }
.session-meta code { font-size: 0.85em; background: #f0f0f0; padding: 1px 6px; border-radius: 3px; }
.session-stats { display: flex; gap: 8px; font-size: 0.8em; color: #888; }
.session-body { padding: 0 16px 14px 16px; border-top: 1px solid #f0f0f0; }
.event-timeline { list-style: none; padding: 8px 0; margin: 0; }
.event-timeline li { padding: 3px 0; font-size: 0.85em; display: flex; gap: 8px; align-items: baseline; }
.event-timeline .event-time { font-family: "SF Mono", Menlo, monospace; color: #888; white-space: nowrap; }
.event-timeline .event-type { display: inline-block; padding: 1px 6px; border-radius: 3px;
                              font-size: 0.8em; font-weight: 500; white-space: nowrap; }
.event-type.container { background: #d1ecf1; color: #0c5460; }
.event-type.app { background: #d4edda; color: #155724; }
.session-logs { max-height: 400px; overflow-y: auto; background: #f8f8f8; border-radius: 6px;
                padding: 8px; margin-top: 8px; }
.session-logs table { margin: 0; box-shadow: none; font-size: 0.82em; }
.session-logs td { padding: 2px 8px; font-family: "SF Mono", Menlo, monospace; font-size: 0.9em; }
.session-logs th { padding: 4px 8px; }
"""


def _event_type_class(event_type: str) -> str:
    """Map event type to CSS class."""
    if event_type.startswith("container"):
        return "container"
    return "app"


def _event_type_label(event_type: str) -> str:
    """Human-readable label for event types."""
    return {
        "container_creating": "Creating",
        "container_started": "Started",
        "container_stopping": "Stopping",
        "container_deleted": "Deleted",
        "app_started": "App Started",
        "app_listening": "App Listening",
        "app_shutdown": "App Shutdown",
    }.get(event_type, event_type)


def _render_sessions_section(
    sessions: list[Session],
    entries: list[InternalLogEntry],
) -> str:
    """Render the Sessions section of the report."""
    # Build entry lookup by session_id for log previews
    entries_by_session: dict[str, list[InternalLogEntry]] = defaultdict(list)
    for e in entries:
        if e.session_id:
            entries_by_session[e.session_id].append(e)

    parts: list[str] = []
    parts.append(f'<details class="issues-wrapper" open>')
    parts.append(f'<summary><div class="issues-toggle">'
                 f'<span class="arrow">&#9654;</span>'
                 f'<h2>Sessions ({len(sessions)})</h2>'
                 f'</div></summary>')
    parts.append(f'<div class="issues-content">')

    for session in sessions:
        is_open = session.end_time is None
        card_cls = "session-card open-session" if is_open else "session-card"
        start_str = session.start_time.strftime("%Y-%m-%d %H:%M:%S")
        end_str = session.end_time.strftime("%H:%M:%S") if session.end_time else "still running"
        duration = _fmt_duration(session.end_time - session.start_time) if session.end_time else "—"
        container_label = session.container_name or "(unnamed)"

        # Count errors/warnings in this session
        session_entries = entries_by_session.get(session.id, [])
        error_count = sum(1 for e in session_entries if e.level is LogLevel.ERROR)
        warn_count = sum(1 for e in session_entries if e.level is LogLevel.WARNING)

        parts.append(f'<details class="{card_cls}">')
        parts.append(f'<summary class="session-header">')
        parts.append(f'<span class="arrow">&#9654;</span>')
        parts.append(f'<div class="session-meta">')
        parts.append(f'<strong>{html.escape(session.id)}</strong>')
        parts.append(f'<code>{html.escape(container_label)}</code>')
        if session.instance:
            parts.append(f'<code>{html.escape(session.instance)}</code>')
        parts.append(f'<span>{start_str} — {end_str}</span>')
        parts.append(f'<span>({duration})</span>')
        parts.append(f'</div>')
        parts.append(f'<div class="session-stats">')
        parts.append(f'<span>{session.entry_count:,} entries</span>')
        if error_count:
            parts.append(f'<span class="badge error">{error_count} errors</span>')
        if warn_count:
            parts.append(f'<span class="badge warning">{warn_count} warnings</span>')
        parts.append(f'</div>')
        parts.append(f'</summary>')

        # Session body: event timeline + log preview
        parts.append(f'<div class="session-body">')

        # Event timeline
        sorted_events = sorted(session.events, key=lambda e: e["timestamp"])
        parts.append(f'<ul class="event-timeline">')
        for ev in sorted_events:
            ev_time = ev["timestamp"].strftime("%H:%M:%S")
            ev_cls = _event_type_class(ev["type"])
            ev_label = _event_type_label(ev["type"])
            parts.append(
                f'<li>'
                f'<span class="event-time">{ev_time}</span>'
                f'<span class="event-type {ev_cls}">{ev_label}</span>'
                f'<span>{html.escape(ev["message"][:120])}</span>'
                f'</li>'
            )
        parts.append(f'</ul>')

        # Log preview table (capped at 100 entries to keep report manageable)
        if session_entries:
            preview = session_entries[:100]
            parts.append(f'<div class="session-logs">')
            parts.append(f'<table><thead><tr>'
                         f'<th>Time</th><th>Level</th><th>Service</th><th>Message</th>'
                         f'</tr></thead><tbody>')
            for e in preview:
                lvl_cls = _level_class(e.level.value)
                ts_str = e.timestamp.strftime("%H:%M:%S")
                msg_short = html.escape(e.message[:200])
                parts.append(
                    f'<tr>'
                    f'<td class="mono">{ts_str}</td>'
                    f'<td><span class="badge {lvl_cls}">{e.level.value}</span></td>'
                    f'<td>{html.escape(e.service)}</td>'
                    f'<td class="msg">{msg_short}</td>'
                    f'</tr>'
                )
            parts.append(f'</tbody></table>')
            if len(session_entries) > 100:
                parts.append(
                    f'<div style="color:#888;font-size:0.85em;padding:4px">'
                    f'... and {len(session_entries) - 100:,} more entries</div>'
                )
            parts.append(f'</div>')

        parts.append(f'</div></details>')

    parts.append("</div></details>")
    return "\n".join(parts)


def generate_report(
    entries: list[InternalLogEntry],
    output_path: Path,
    sessions: Optional[list[Session]] = None,
) -> Path:
    """Generate report.html alongside the merged output."""
    summary = _build_summary(entries)
    if summary["total"] == 0:
        output_path.write_text("<html><body><p>No log entries.</p></body></html>")
        return output_path

    total = summary["total"]
    entity_counts = _count_by(entries, "entity")
    level_counts = _count_by(entries, "level")
    service_counts = _count_by(entries, "service")
    level_by_svc = _level_by_service(entries)
    entity_ranges = _entity_time_ranges(entries)
    hourly = _hourly_histogram(entries)
    errors = _errors_detail(entries)

    level_colors = {
        "ERROR": "#e74c3c", "WARNING": "#f39c12",
        "INFO": "#3498db", "DEBUG": "#95a5a6", "UNKNOWN": "#bdc3c7",
    }

    # --- Build HTML ---
    parts: list[str] = []
    parts.append(f"<!DOCTYPE html><html><head><meta charset='utf-8'>")
    parts.append(f"<title>Log Report — {summary['earliest'].strftime('%Y-%m-%d')}</title>")
    parts.append(f"<style>{_CSS}</style></head><body>")
    parts.append(f"<h1>Azure Web App Log Report</h1>")
    parts.append(f"<div class='subtitle'>{summary['earliest'].strftime('%Y-%m-%d %H:%M')} — "
                 f"{summary['latest'].strftime('%Y-%m-%d %H:%M')} CST &nbsp;·&nbsp; "
                 f"{_fmt_duration(summary['span'])} span</div>")

    # Summary cards
    error_count = sum(1 for e in entries if e.level is LogLevel.ERROR)
    warn_count = sum(1 for e in entries if e.level is LogLevel.WARNING)
    parts.append('<div class="cards">')
    for label, value in [
        ("Total Entries", f"{total:,}"),
        ("Source Files", str(summary["source_files"])),
        ("Errors", f'<span style="color:#e74c3c">{error_count:,}</span>'),
        ("Warnings", f'<span style="color:#f39c12">{warn_count:,}</span>'),
        ("Services", str(len(service_counts))),
    ]:
        parts.append(f'<div class="card"><div class="label">{label}</div><div class="value">{value}</div></div>')
    parts.append("</div>")

    # --- Issues (Errors & Warnings) — prominent, right after summary ---
    issues = _group_issues(entries)
    if issues:
        error_issues = [i for i in issues if i["level"] == "ERROR"]
        warn_issues = [i for i in issues if i["level"] == "WARNING"]
        parts.append(f'<details class="issues-wrapper" open>')
        parts.append(f'<summary><div class="issues-toggle">'
                     f'<span class="arrow">&#9654;</span>'
                     f'<h2>Issues ({len(error_issues)} error types, {len(warn_issues)} warning types)</h2>'
                     f'</div></summary>')
        parts.append(f'<div class="issues-content">')
        for issue in issues:
            card_cls = "error-card" if issue["level"] == "ERROR" else "warning-card"
            badge_cls = _level_class(issue["level"])
            # Use <details> for native expand/collapse
            parts.append(f'<details class="issue-card {card_cls}">')
            parts.append(f'<summary class="issue-header">')
            parts.append(f'<span class="arrow">&#9654;</span>')
            parts.append(f'<span class="badge {badge_cls}">{html.escape(issue["level"])}</span>')
            parts.append(f'<span class="issue-count">{issue["count"]}x</span>')
            parts.append(f'<div class="issue-meta">')
            parts.append(f'<span class="issue-sig">{html.escape(issue["signature"])}</span>')
            parts.append(f'</div>')
            parts.append(f'<code style="font-size:0.8em;color:#888">{html.escape(issue["service"])}</code>')
            parts.append(f'</summary>')
            parts.append(f'<div class="issue-body">')
            # Tags
            parts.append(f'<div class="issue-tags">')
            parts.append(f'<code>{html.escape(issue["entity"])}</code>')
            parts.append(f'<code>{html.escape(issue["service"])}</code>')
            first_str = issue["first"].strftime("%Y-%m-%d %H:%M:%S")
            last_str = issue["last"].strftime("%Y-%m-%d %H:%M:%S")
            if issue["count"] > 1:
                parts.append(f'<code>{first_str} — {last_str}</code>')
            else:
                parts.append(f'<code>{first_str}</code>')
            parts.append(f'</div>')
            # Full message
            parts.append(f'<pre>{html.escape(issue["full_message"])}</pre>')
            # Occurrences table (if > 1, show each timestamp)
            if issue["count"] > 1:
                occ_sorted = sorted(issue["occurrences"], key=lambda e: e.timestamp, reverse=True)
                parts.append('<table class="occ-table"><thead><tr>'
                             '<th>Time</th><th>Source</th></tr></thead><tbody>')
                for occ in occ_sorted[:25]:
                    parts.append(f'<tr><td class="mono">{occ.timestamp.strftime("%Y-%m-%d %H:%M:%S")}</td>'
                                 f'<td class="mono">{html.escape(occ.source_file)}:{occ.line_number}</td></tr>')
                if len(occ_sorted) > 25:
                    parts.append(f'<tr><td colspan="2" style="color:#888">... and {len(occ_sorted) - 25} more</td></tr>')
                parts.append('</tbody></table>')
            else:
                occ = issue["occurrences"][0]
                parts.append(f'<div style="font-size:0.85em;color:#666;margin-top:4px">'
                             f'Source: <code>{html.escape(occ.source_file)}:{occ.line_number}</code></div>')
            parts.append('</div></details>')
        parts.append("</div></details>")
    else:
        parts.append('<div class="no-issues">No errors or warnings found.</div>')

    # --- Sessions ---
    if sessions:
        parts.append(_render_sessions_section(sessions, entries))

    # Entries by Entity
    parts.append('<div class="section"><h2>Entries by Entity</h2>')
    max_entity = max(c for _, c in entity_counts) if entity_counts else 1
    rows = []
    for name, count in entity_counts:
        rows.append([
            f"<code>{html.escape(name)}</code>",
            f"{count:,}",
            _pct(count, total),
            _bar(count, max_entity),
        ])
    parts.append(_render_table(["Entity", "Count", "%", ""], rows))
    parts.append("</div>")

    # Entity Time Ranges
    parts.append('<div class="section"><h2>Entity Time Coverage</h2>')
    rows = []
    for name, lo, hi, span in entity_ranges:
        rows.append([
            f"<code>{html.escape(name)}</code>",
            lo.strftime("%m-%d %H:%M"),
            hi.strftime("%m-%d %H:%M"),
            _fmt_duration(span),
        ])
    parts.append(_render_table(["Entity", "Earliest", "Latest", "Span"], rows))
    parts.append("</div>")

    # Entries by Log Level
    parts.append('<div class="section"><h2>Entries by Log Level</h2>')
    max_level = max(c for _, c in level_counts) if level_counts else 1
    rows = []
    for name, count in level_counts:
        color = level_colors.get(name, "#999")
        rows.append([
            f'<span class="badge {_level_class(name)}">{html.escape(name)}</span>',
            f"{count:,}",
            _pct(count, total),
            _bar(count, max_level, color),
        ])
    parts.append(_render_table(["Level", "Count", "%", ""], rows))
    parts.append("</div>")

    # Top Services
    parts.append('<div class="section"><h2>Top Services</h2>')
    max_svc = max(c for _, c in service_counts[:20]) if service_counts else 1
    rows = []
    for name, count in service_counts[:20]:
        svc_levels = level_by_svc.get(name, Counter())
        badges = ""
        for lvl in ["ERROR", "WARNING"]:
            if svc_levels.get(lvl, 0) > 0:
                badges += f' <span class="badge {_level_class(lvl)}">{svc_levels[lvl]}</span>'
        rows.append([
            f"<code>{html.escape(name)}</code>",
            f"{count:,}",
            _pct(count, total),
            badges or "—",
            _bar(count, max_svc),
        ])
    parts.append(_render_table(["Service", "Count", "%", "Errors/Warnings", ""], rows))
    if len(service_counts) > 20:
        parts.append(f'<div style="color:#888;font-size:0.85em">... and {len(service_counts) - 20} more services</div>')
    parts.append("</div>")

    # Level Breakdown by Service (only services with errors or warnings)
    notable = {svc for svc, counts in level_by_svc.items()
               if counts.get("ERROR", 0) > 0 or counts.get("WARNING", 0) > 0}
    if notable:
        parts.append('<div class="section"><h2>Error/Warning Breakdown by Service</h2>')
        rows = []
        for svc in sorted(notable):
            counts = level_by_svc[svc]
            svc_total = sum(counts.values())
            rows.append([
                f"<code>{html.escape(svc)}</code>",
                f'{counts.get("ERROR", 0):,}',
                f'{counts.get("WARNING", 0):,}',
                f'{counts.get("INFO", 0):,}',
                f'{counts.get("DEBUG", 0):,}',
                f"{svc_total:,}",
            ])
        rows.sort(key=lambda r: -int(r[1].replace(",", "")))
        parts.append(_render_table(["Service", "Errors", "Warnings", "Info", "Debug", "Total"], rows))
        parts.append("</div>")

    # Hourly Activity
    if hourly:
        parts.append('<div class="section"><h2>Hourly Activity</h2>')
        max_hour = max(c for _, c in hourly)
        rows = []
        for hour_label, count in hourly:
            rows.append([
                f'<span class="mono">{html.escape(hour_label)}</span>',
                f"{count:,}",
                _bar(count, max_hour, "#4a90d9"),
            ])
        parts.append(_render_table(["Hour (UTC)", "Count", ""], rows))
        parts.append("</div>")

    parts.append("</body></html>")
    output_path.write_text("\n".join(parts), encoding="utf-8")
    print(f"Report: {output_path}")
    return output_path
