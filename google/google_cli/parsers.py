"""Parsing and formatting utilities for Google CLI."""
from datetime import datetime, timezone


def format_local_time(timestamp: str) -> str:
    """Format an ISO timestamp to local timezone short format (e.g., 'Jan 13 14:30').

    Args:
        timestamp: ISO 8601 timestamp string (e.g., '2025-01-13T14:30:45Z' or '2025-01-13T14:30:45.000+00:00')

    Returns:
        Formatted string in local timezone, or original string if parsing fails.
    """
    if not timestamp:
        return ""
    try:
        # Handle various ISO formats
        ts = timestamp.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        local_dt = dt.astimezone()
        return local_dt.strftime("%b %d %H:%M")
    except (ValueError, TypeError):
        return timestamp


def format_local_time_only(timestamp: str) -> str:
    """Format an ISO timestamp to local timezone time-only format (e.g., '14:30:45').

    Args:
        timestamp: ISO 8601 timestamp string

    Returns:
        Formatted time string in local timezone, or original string if parsing fails.
    """
    if not timestamp:
        return ""
    try:
        ts = timestamp.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        local_dt = dt.astimezone()
        return local_dt.strftime("%H:%M:%S")
    except (ValueError, TypeError):
        return timestamp
