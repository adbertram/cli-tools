"""Formatting helpers for Pinterest CLI output."""

from datetime import datetime, timezone


def format_local_time(timestamp: str, format: str = "%b %d %H:%M") -> str:
    """Convert an API timestamp to local time for table display."""
    if not timestamp:
        return ""

    if timestamp.endswith("Z"):
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    else:
        dt = datetime.fromisoformat(timestamp)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone().strftime(format)


def format_local_time_only(timestamp: str) -> str:
    """Convert an API timestamp to local time and return only the time portion."""
    return format_local_time(timestamp, "%H:%M:%S")
