"""Parse human-readable duration strings into timedeltas."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

_DURATION_RE = re.compile(r"^(\d+)([hdw])$")


def parse_since(value: str) -> timedelta | None:
    """Convert '24h', '3d', '1w' to timedelta; 'all' returns None."""
    if value == "all":
        return None

    m = _DURATION_RE.match(value)
    if not m:
        raise ValueError(f"Invalid duration: '{value}'. Use e.g. 24h, 3d, 1w, or all")

    amount, unit = int(m.group(1)), m.group(2)
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "d":
        return timedelta(days=amount)
    if unit == "w":
        return timedelta(weeks=amount)


def cutoff_from_since(since: str) -> datetime | None:
    """Return cutoff datetime, or None for 'all'."""
    delta = parse_since(since)
    if delta is None:
        return None
    return datetime.now() - delta
