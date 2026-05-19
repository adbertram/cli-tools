"""Parsing and formatting utilities."""
from datetime import datetime, timezone
from typing import Optional


def format_local_time(timestamp: Optional[str]) -> str:
    """Format a Unix timestamp or ISO string to local time: 'Jan 13 14:30'.

    Args:
        timestamp: Unix timestamp string or ISO datetime string

    Returns:
        Formatted local time string, or empty string if invalid
    """
    if not timestamp:
        return ""
    try:
        ts = float(timestamp)
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
        return dt.strftime("%b %d %H:%M")
    except (ValueError, TypeError, OSError):
        pass
    try:
        dt = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")).astimezone()
        return dt.strftime("%b %d %H:%M")
    except (ValueError, TypeError):
        return str(timestamp)


def format_local_time_only(timestamp: Optional[str]) -> str:
    """Format a Unix timestamp or ISO string to local time only: '14:30:45'.

    Args:
        timestamp: Unix timestamp string or ISO datetime string

    Returns:
        Formatted time-only string, or empty string if invalid
    """
    if not timestamp:
        return ""
    try:
        ts = float(timestamp)
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
        return dt.strftime("%H:%M:%S")
    except (ValueError, TypeError, OSError):
        pass
    try:
        dt = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")).astimezone()
        return dt.strftime("%H:%M:%S")
    except (ValueError, TypeError):
        return str(timestamp)
