"""Display parsers for Crypto.com Exchange CLI."""
from datetime import datetime
from typing import Union


def _timestamp_seconds(timestamp: Union[str, int, float]) -> float:
    """Convert a Crypto.com timestamp value to epoch seconds."""
    if isinstance(timestamp, str):
        value = timestamp.strip()
        if not value:
            raise ValueError("Timestamp cannot be empty")
        if value.isdigit():
            timestamp = int(value)
        else:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()

    if isinstance(timestamp, bool):
        raise TypeError("Timestamp cannot be a boolean")
    if not isinstance(timestamp, (int, float)):
        raise TypeError(f"Expected timestamp string or number, got {type(timestamp).__name__}")

    absolute = abs(timestamp)
    if absolute >= 1_000_000_000_000_000:
        return timestamp / 1_000_000_000
    if absolute >= 1_000_000_000_000:
        return timestamp / 1_000
    return float(timestamp)


def format_local_time(timestamp: Union[str, int, float], format: str = "%b %d %H:%M") -> str:
    """Format an epoch or ISO timestamp in local time."""
    return datetime.fromtimestamp(_timestamp_seconds(timestamp)).strftime(format)


def format_local_time_only(timestamp: Union[str, int, float]) -> str:
    """Format an epoch or ISO timestamp as local time only."""
    return format_local_time(timestamp, "%H:%M:%S")
