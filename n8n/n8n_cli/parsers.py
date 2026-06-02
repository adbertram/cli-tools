"""Output parsing utilities for n8n CLI."""
from datetime import datetime


def format_local_time(timestamp: str, format: str = '%b %d %H:%M') -> str:
    """Convert an ISO timestamp to local timezone and format it.

    Args:
        timestamp: ISO format timestamp (e.g., "2025-01-13T14:30:45Z")
        format: strftime format string (default: "Jan 13 14:30")

    Returns:
        Formatted time string in local timezone, or original timestamp if parsing fails
    """
    if not timestamp:
        return ''

    try:
        if timestamp.endswith('Z'):
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        else:
            dt = datetime.fromisoformat(timestamp)

        local_dt = dt.astimezone()
        return local_dt.strftime(format)
    except (ValueError, AttributeError):
        return timestamp[:16] if len(timestamp) > 16 else timestamp


def format_local_time_only(timestamp: str) -> str:
    """Convert an ISO timestamp to local timezone and return just the time portion."""
    return format_local_time(timestamp, '%H:%M:%S')
