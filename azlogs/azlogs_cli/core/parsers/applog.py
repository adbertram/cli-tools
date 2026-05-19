"""Parser for application logs (ciem.log)."""
from __future__ import annotations

import re
from datetime import datetime

from ...models import Entity, LogLevel
from ..types import ClassifiedLogFile, InternalLogEntry
from . import collect_multiline, normalize_level, parse_bracketed_timestamp

_HEADER_RE = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)\]"
    r" \[(\w+)\]"
    r" \[([^\]]+)\]"
    r" ?(.*)"
)


def _starts_new_entry(line: str) -> bool:
    return line.startswith("[") and parse_bracketed_timestamp(line) is not None


def parse_app_log_header(line: str) -> tuple[datetime, LogLevel, str, str] | None:
    m = _HEADER_RE.match(line)
    if not m:
        return None
    ts_str, level_str, component, message = m.groups()
    frac_parts = ts_str.split(".")
    base = frac_parts[0]
    frac = frac_parts[1] if len(frac_parts) > 1 else "0"
    frac = frac[:6].ljust(6, "0")
    ts = datetime.fromisoformat(f"{base.replace(' ', 'T')}.{frac}")
    return ts, normalize_level(level_str), component, message


def parse(file: ClassifiedLogFile) -> list[InternalLogEntry]:
    """Parse ciem.log application log file."""
    content = file.path.read_text(encoding="utf-8", errors="replace")
    raw_lines = content.splitlines()
    if not raw_lines:
        return []

    entries: list[InternalLogEntry] = []
    grouped = collect_multiline(raw_lines, _starts_new_entry)

    for start_line, block_text in grouped:
        block_lines = block_text.split("\n")
        first_line = block_lines[0]

        parsed = parse_app_log_header(first_line)
        if not parsed:
            continue

        ts, level, service, msg = parsed

        if len(block_lines) > 1:
            full_msg = "\n".join([msg] + block_lines[1:])
        else:
            full_msg = msg

        entries.append(InternalLogEntry(
            timestamp=ts, entity=Entity.APP_LOG, service=service, instance=None,
            container=None, level=level, message=full_msg,
            source_file=file.relative_path, line_number=start_line,
        ))

    return entries
