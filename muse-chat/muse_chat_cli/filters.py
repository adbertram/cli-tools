"""Standard client-side filtering for browser-derived chat records."""

from __future__ import annotations

from typing import Optional

from cli_tools_shared.filters import OPERATORS, apply_filters, validate_filters


def filter_rows(rows: list[dict], filters: Optional[list[str]]) -> list[dict]:
    """Validate standard filter syntax, then filter browser-derived records."""
    if not filters:
        return rows
    validate_filters(filters)
    return apply_filters(rows, filters)
