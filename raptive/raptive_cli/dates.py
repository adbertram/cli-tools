"""Date parsing utilities for Raptive CLI.

Converts period presets to date ranges and validates date formats.
"""
from datetime import datetime, timedelta
from typing import Tuple


def parse_period(period: str) -> Tuple[str, str]:
    """Convert a period preset to start and end dates.

    Args:
        period: One of: yesterday, last7d, last30d, mtd (month-to-date)

    Returns:
        Tuple of (start_date, end_date) in YYYY-MM-DD format.

    Raises:
        ValueError: If period is not recognized.
    """
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)

    if period == "yesterday":
        return (yesterday.isoformat(), yesterday.isoformat())

    elif period == "last7d":
        start = today - timedelta(days=7)
        return (start.isoformat(), yesterday.isoformat())

    elif period == "last30d":
        start = today - timedelta(days=30)
        return (start.isoformat(), yesterday.isoformat())

    elif period == "mtd":
        # Month to date: from 1st of current month to yesterday
        start = today.replace(day=1)
        return (start.isoformat(), yesterday.isoformat())

    elif period == "lastmonth":
        # Last month: from 1st to last day of the previous month
        # Get 1st of current month, then go back 1 day to get last day of previous month
        first_of_current = today.replace(day=1)
        last_of_previous = first_of_current - timedelta(days=1)
        first_of_previous = last_of_previous.replace(day=1)
        return (first_of_previous.isoformat(), last_of_previous.isoformat())

    else:
        raise ValueError(
            f"Unknown period: {period}. "
            "Valid options: yesterday, last7d, last30d, mtd, lastmonth"
        )


def validate_date(date_str: str) -> str:
    """Validate a date string is in YYYY-MM-DD format.

    Args:
        date_str: Date string to validate.

    Returns:
        The validated date string.

    Raises:
        ValueError: If date format is invalid.
    """
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    except ValueError:
        raise ValueError(
            f"Invalid date format: {date_str}. Use YYYY-MM-DD format."
        )


def get_date_range(
    period: str = None,
    start: str = None,
    end: str = None,
) -> Tuple[str, str]:
    """Get a date range from either a period preset or explicit dates.

    Args:
        period: Period preset (yesterday, last7d, last30d, mtd)
        start: Explicit start date (YYYY-MM-DD)
        end: Explicit end date (YYYY-MM-DD)

    Returns:
        Tuple of (start_date, end_date) in YYYY-MM-DD format.

    Raises:
        ValueError: If neither period nor both start/end are provided.
    """
    if start and end:
        # Use explicit dates
        return (validate_date(start), validate_date(end))
    elif period:
        # Use period preset
        return parse_period(period)
    else:
        # Default to last30d
        return parse_period("last30d")
