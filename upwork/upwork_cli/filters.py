"""Data-driven filter map for Upwork ``jobs`` search.

The Upwork GraphQL ``MarketplaceJobPostingsSearchFilter`` input type uses
suffixed field names (for example ``skillExpression_eq`` and ``locations_any``).
The complete input type must be introspected from Upwork's GraphQL Explorer once
API keys are available, so this module keeps the standard-CLI -> API mapping in a
single declarative table. Adding or correcting a filter is a one-line data edit
in ``JOBS_FILTER_FIELDS``.

Standard CLI filter fields use the shared ``field:op:value`` syntax and are
translated to the GraphQL filter input by :func:`build_jobs_filter_input`.
Fields the API cannot express server-side are marked ``server_side=False`` and
applied client-side by the jobs client against the normalized node records.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

# Re-export the shared filtering primitives so callers get the standard
# ``field:op:value`` operator set and client-side matcher from one place. The
# jobs client applies ``apply_filters`` for client-side-only fields, and
# ``OPERATORS`` is the canonical operator whitelist used by ``--filter`` help.
from cli_tools_shared.filters import (
    FilterValidationError,
    OPERATORS,
    apply_filters,
    parse_filter_string,
    validate_filters,
)

__all__ = [
    "ALLOWED_FILTER_FIELDS",
    "FilterValidationError",
    "JOBS_FILTER_FIELDS",
    "JobsFilterField",
    "OPERATORS",
    "apply_filters",
    "build_jobs_filter_input",
    "get_filter_field",
    "split_server_and_client_filters",
    "validate_jobs_filters",
]


@dataclass(frozen=True)
class JobsFilterField:
    """One declarative filter mapping.

    Attributes:
        cli_field: Standard CLI filter field name (left of ``field:op:value``).
        api_field: GraphQL ``MarketplaceJobPostingsSearchFilter`` input key, or
            ``None`` when the field is client-side only.
        server_side: Whether the API expresses this filter. When ``False`` the
            jobs client applies it against normalized node records.
        record_path: Dotted path into the normalized job record used for
            client-side matching (defaults to ``cli_field``).
        to_api: Optional callable ``(op, value) -> {api_key: api_value}`` that
            builds the GraphQL filter fragment for this field. Defaults to
            ``{api_field: value}`` for single-value fields.
        help: Short human description for documentation and errors.
    """

    cli_field: str
    api_field: Optional[str] = None
    server_side: bool = True
    record_path: Optional[str] = None
    to_api: Optional[Callable[[str, str], dict]] = None
    help: str = ""


def _split_list(value: str) -> list[str]:
    """Split a pipe/comma separated string into trimmed, non-empty parts."""
    return [part.strip() for part in value.replace("|", ",").split(",") if part.strip()]


def _comma_join(op: str, value: str) -> str:
    """Normalize a pipe/comma list into a comma-joined API expression."""
    return ",".join(_split_list(value))


def _skill_expression(op: str, value: str) -> dict:
    return {"skillExpression_eq": _comma_join(op, value)}


def _locations_any(op: str, value: str) -> dict:
    return {"locations_any": _split_list(value)}


def _title_expression(op: str, value: str) -> dict:
    return {"titleExpression_eq": value}


def _category_any(op: str, value: str) -> dict:
    return {"categoryIds_any": _split_list(value)}


# ---------------------------------------------------------------------------
# The single source of truth for jobs filtering.
#
# Adding a new server-side filter = append one JobsFilterField row. Values here
# reflect known/partial schema fields; correct or extend them after live
# GraphQL introspection without touching command or client code.
# ---------------------------------------------------------------------------
JOBS_FILTER_FIELDS: tuple[JobsFilterField, ...] = (
    JobsFilterField(
        "query",
        api_field="titleExpression_eq",
        to_api=_title_expression,
        help="Free-text search across job title/description.",
    ),
    JobsFilterField(
        "skills",
        api_field="skillExpression_eq",
        to_api=_skill_expression,
        help="Comma or pipe separated skill slugs (skillExpression_eq).",
    ),
    JobsFilterField(
        "category",
        api_field="categoryIds_any",
        to_api=_category_any,
        help="Category/occupation ids (categoryIds_any).",
    ),
    JobsFilterField(
        "client_location",
        api_field="locations_any",
        to_api=_locations_any,
        help="Client country/location names (locations_any).",
    ),
    JobsFilterField(
        "job_type",
        server_side=False,
        record_path="job_type",
        help="hourly | fixed (client-side until schema confirms API field).",
    ),
    JobsFilterField(
        "experience_level",
        server_side=False,
        record_path="experience_level",
        help="entry | intermediate | expert (client-side).",
    ),
    JobsFilterField(
        "fixed_min",
        server_side=False,
        record_path="fixed_budget",
        help="Minimum fixed-price budget (client-side, use fixed_min:gte:VALUE).",
    ),
    JobsFilterField(
        "fixed_max",
        server_side=False,
        record_path="fixed_budget",
        help="Maximum fixed-price budget (client-side, use fixed_max:lte:VALUE).",
    ),
    JobsFilterField(
        "hourly_min",
        server_side=False,
        record_path="hourly_min",
        help="Minimum hourly rate (client-side, use hourly_min:gte:VALUE).",
    ),
    JobsFilterField(
        "hourly_max",
        server_side=False,
        record_path="hourly_max",
        help="Maximum hourly rate (client-side, use hourly_max:lte:VALUE).",
    ),
    JobsFilterField(
        "posted_after",
        server_side=False,
        record_path="published_datetime",
        help="Only jobs published on/after an ISO date (client-side, posted_after:gte:DATE).",
    ),
)

_FIELDS_BY_CLI = {f.cli_field: f for f in JOBS_FILTER_FIELDS}

ALLOWED_FILTER_FIELDS = frozenset(_FIELDS_BY_CLI)


def get_filter_field(cli_field: str) -> Optional[JobsFilterField]:
    """Return the declarative mapping for a CLI filter field, if defined."""
    return _FIELDS_BY_CLI.get(cli_field)


def validate_jobs_filters(filters: Optional[list[str]]) -> None:
    """Validate jobs filter strings against the allowed field set.

    Raises:
        FilterValidationError: If a filter references an unknown field or uses
            invalid ``field:op:value`` syntax.
    """
    if not filters:
        return
    validate_filters(filters, ALLOWED_FILTER_FIELDS)


def split_server_and_client_filters(
    filters: Optional[list[str]],
) -> tuple[list[str], list[str]]:
    """Partition filter strings into server-side and client-side lists.

    Returns:
        ``(server_filters, client_filters)`` where each element is the original
        ``field:op:value`` string.
    """
    server: list[str] = []
    client: list[str] = []
    for raw in filters or []:
        field_name, _op, _value = parse_filter_string(raw)[0]
        mapping = _FIELDS_BY_CLI.get(field_name)
        if mapping is not None and mapping.server_side:
            server.append(raw)
        else:
            client.append(raw)
    return server, client


def build_jobs_filter_input(server_filters: list[str]) -> dict[str, Any]:
    """Build the GraphQL ``MarketplaceJobPostingsSearchFilter`` input dict.

    Only server-side filter fields contribute. Each field's ``to_api`` callable
    (or its default single-value mapping) produces a fragment that is merged
    into the returned filter input.

    Raises:
        FilterValidationError: If a server filter references a field with no API
            mapping (an internal misconfiguration that must fail loudly).
    """
    filter_input: dict[str, Any] = {}
    for raw in server_filters:
        field_name, op, value = parse_filter_string(raw)[0]
        mapping = _FIELDS_BY_CLI.get(field_name)
        if mapping is None or not mapping.server_side:
            raise FilterValidationError(
                f"Filter field '{field_name}' is not a server-side jobs filter."
            )
        if value is None:
            raise FilterValidationError(
                f"Filter field '{field_name}' requires a value (field:op:value)."
            )
        if mapping.to_api is not None:
            fragment = mapping.to_api(op, value)
        elif mapping.api_field is not None:
            fragment = {mapping.api_field: value}
        else:
            raise FilterValidationError(
                f"Filter field '{field_name}' has no API mapping."
            )
        filter_input.update(fragment)
    return filter_input
