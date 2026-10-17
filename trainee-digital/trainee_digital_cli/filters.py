"""Order-record filtering for the trainee-digital CLI.

trainee.digital's /api/orders endpoint exposes no server-side filtering, so
`tasks list --filter` is applied client-side against the fetched rows using the
standard shared ``field:op:value`` operator set. This module adds the one piece
of site knowledge that callers need: the fixed set of fields a normalized
order record carries (every key in the captured live /orders payloads in
tests/fixtures/orders_list.json plus the derived ``url``), enforced through
``validate_filters(allowed_fields=...)`` so a filter on a typo'd field is a
loud error instead of a silently empty result.
"""

from __future__ import annotations

from typing import List, Optional

from cli_tools_shared.filters import (
    FilterValidationError,
    OPERATORS,
    apply_filters,
    parse_filter_string,
    validate_filters,
)

# Fields that exist on normalized order records (list rows from the live
# GET /api/orders capture plus the derived url). Anything else is a typo.
ALLOWED_ORDER_FILTER_FIELDS = frozenset({
    "id", "title", "category", "pay", "unit", "volume", "deadline",
    "posted", "url",
})

__all__ = [
    "ALLOWED_ORDER_FILTER_FIELDS",
    "FilterValidationError",
    "OPERATORS",
    "apply_filters",
    "parse_filter_string",
    "validate_filters",
    "validate_order_filters",
]


def validate_order_filters(filters: Optional[List[str]]) -> None:
    """Validate ``field:op:value`` syntax and the order-record field allowlist.

    Raises:
        FilterValidationError: for malformed filters or a filter on a field no
            order record carries.
    """
    if not filters:
        return
    validate_filters(filters, allowed_fields=ALLOWED_ORDER_FILTER_FIELDS)
