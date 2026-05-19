"""Parser registry and shared helpers."""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from ...models import Entity, LogLevel
from ..types import ClassifiedLogFile, InternalLogEntry

# All Azure logs are UTC — convert to Central Time for display
_LOCAL_TZ = ZoneInfo("America/Chicago")

# ISO timestamp: 2026-02-10T08:49:10.8684193Z
_ISO_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?Z?")

# Bracketed timestamp: [2026-02-03 19:25:29.439]
_BRACKETED_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:\.(\d+))?\]")

# Kudu timestamp: 2026-02-04T20:01:55  (seconds precision, double-space after)
_KUDU_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})  ")

_LEVEL_MAP: dict[str, LogLevel] = {
    "inf": LogLevel.INFO,
    "info": LogLevel.INFO,
    "wrn": LogLevel.WARNING,
    "warn": LogLevel.WARNING,
    "warning": LogLevel.WARNING,
    "err": LogLevel.ERROR,
    "error": LogLevel.ERROR,
    "fail": LogLevel.ERROR,
    "dbg": LogLevel.DEBUG,
    "debug": LogLevel.DEBUG,
}


def _utc_to_local(dt: datetime) -> datetime:
    """Convert a naive UTC datetime to local time (America/Chicago)."""
    return dt.replace(tzinfo=timezone.utc).astimezone(_LOCAL_TZ).replace(tzinfo=None)


def parse_iso_timestamp(s: str) -> datetime | None:
    """Parse ISO timestamp from start of string, converted to local time."""
    m = _ISO_RE.match(s)
    if not m:
        return None
    base = m.group(1)
    frac = m.group(2) or "0"
    frac = frac[:6].ljust(6, "0")
    return _utc_to_local(datetime.fromisoformat(f"{base}.{frac}"))


def parse_bracketed_timestamp(s: str) -> datetime | None:
    """Parse [YYYY-MM-DD HH:MM:SS.fff] timestamp, converted to local time."""
    m = _BRACKETED_RE.match(s)
    if not m:
        return None
    base = m.group(1)
    frac = m.group(2) or "0"
    frac = frac[:6].ljust(6, "0")
    return _utc_to_local(datetime.fromisoformat(f"{base.replace(' ', 'T')}.{frac}"))


def parse_kudu_timestamp(s: str) -> datetime | None:
    """Parse kudu trace timestamp (seconds precision, double-space separator), converted to local time."""
    m = _KUDU_TS_RE.match(s)
    if not m:
        return None
    return _utc_to_local(datetime.fromisoformat(m.group(1)))


def normalize_level(raw: str) -> LogLevel:
    """Map raw level string to LogLevel enum."""
    return _LEVEL_MAP.get(raw.lower().strip(), LogLevel.UNKNOWN)


def collect_multiline(
    lines: list[str],
    starts_new_entry: Callable[[str], bool],
) -> list[tuple[int, str]]:
    """Group consecutive lines into logical entries.

    Returns list of (1-indexed start_line_number, joined_text).
    """
    entries: list[tuple[int, str]] = []
    current_start: int | None = None
    current_parts: list[str] = []

    for i, line in enumerate(lines):
        line_num = i + 1

        if starts_new_entry(line):
            if current_start is not None:
                entries.append((current_start, "\n".join(current_parts)))
            current_start = line_num
            current_parts = [line]
        else:
            if current_start is None:
                current_start = line_num
                current_parts = [line]
            else:
                current_parts.append(line)

    if current_start is not None:
        entries.append((current_start, "\n".join(current_parts)))

    return entries


def parser_for(entity: Entity) -> Callable[[ClassifiedLogFile], list[InternalLogEntry]]:
    """Return the appropriate parser function for an entity type."""
    from . import applog, container, kudu, platform

    _PARSERS: dict[Entity, Callable[[ClassifiedLogFile], list[InternalLogEntry]]] = {
        Entity.PLATFORM_ORCHESTRATOR: platform.parse,
        Entity.APP_CONTAINER: container.parse,
        Entity.SCM_SIDECAR: container.parse,
        Entity.APP_LOG: applog.parse,
        Entity.KUDU_TRACE: kudu.parse,
    }
    return _PARSERS[entity]
