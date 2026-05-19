"""Output parsing utilities for Hyvor CLI."""
from datetime import datetime, timezone
from typing import Union


def format_local_time(timestamp: Union[str, int, float], format: str = '%b %d %H:%M') -> str:
    """
    Convert a timestamp to local timezone and format it.

    Handles both Unix timestamps (int/float) and ISO format strings.

    Args:
        timestamp: Unix timestamp or ISO format timestamp string
        format: strftime format string (default: "Jan 13 14:30")

    Returns:
        Formatted time string in local timezone, or original value if parsing fails
    """
    if not timestamp:
        return ''

    try:
        if isinstance(timestamp, (int, float)):
            dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        elif isinstance(timestamp, str):
            if timestamp.endswith('Z'):
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            else:
                dt = datetime.fromisoformat(timestamp)
        else:
            return str(timestamp)

        local_dt = dt.astimezone()
        return local_dt.strftime(format)
    except (ValueError, AttributeError, OSError):
        return str(timestamp)[:16] if len(str(timestamp)) > 16 else str(timestamp)


def format_local_time_only(timestamp: Union[str, int, float]) -> str:
    """Convert a timestamp to local timezone and return just the time portion."""
    return format_local_time(timestamp, '%H:%M:%S')
