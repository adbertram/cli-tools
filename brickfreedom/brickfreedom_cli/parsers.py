"""Output parsing utilities for Brickfreedom CLI.

Provides functions to parse JSON-or-text output and extract
structured data from page snapshots and command results.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def format_local_time(timestamp: str) -> str:
    """Format an ISO timestamp to local time as 'Jan 13 14:30'.

    Args:
        timestamp: ISO 8601 timestamp string (e.g., '2025-01-13T14:30:45Z')

    Returns:
        Formatted local time string (e.g., 'Jan 13 14:30')
    """
    if not timestamp:
        return ""
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        local_dt = dt.astimezone()
        return local_dt.strftime("%b %d %H:%M")
    except (ValueError, TypeError):
        return timestamp


def format_local_time_only(timestamp: str) -> str:
    """Format an ISO timestamp to local time-only as 'HH:MM:SS'.

    Args:
        timestamp: ISO 8601 timestamp string

    Returns:
        Formatted time string (e.g., '14:30:45')
    """
    if not timestamp:
        return ""
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        local_dt = dt.astimezone()
        return local_dt.strftime("%H:%M:%S")
    except (ValueError, TypeError):
        return timestamp


def parse_cli_output(output: str) -> Any:
    """Parse CLI output, auto-detecting format.

    Attempts JSON parsing first, falls back to raw string.

    Args:
        output: Raw stdout from a CLI command

    Returns:
        Parsed data (dict, list, or raw string)
    """
    import json
    text = output.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text


def parse_snapshot_items(snapshot_text: str, pattern: str) -> List[Dict[str, str]]:
    """Extract items from a page snapshot using a regex pattern.

    Args:
        snapshot_text: Raw snapshot text from a page snapshot
        pattern: Regex pattern with named groups to extract

    Returns:
        List of dicts with matched group values
    """
    import re
    results = []
    for match in re.finditer(pattern, snapshot_text):
        results.append(match.groupdict())
    return results
