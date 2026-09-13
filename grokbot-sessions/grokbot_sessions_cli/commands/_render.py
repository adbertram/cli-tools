"""Shared post-processing and table formatting for list and get commands.

Each list command applies ``--filter`` itself through :func:`apply_row_filters`
so the filtering stays visible at the command site; this module owns the shared
filter/property validation and what is purely presentational: ``--properties``
selection and table column formatting.
"""
import json
from typing import Any, Dict, List, Optional, Sequence

import typer
from cli_tools_shared.filters import apply_filters, apply_properties_filter, get_nested_value
from cli_tools_shared.output import print_table

from ..parsers import format_local_time

# Table timestamps carry the date because transcripts are queried across days.
TABLE_TIME_FORMAT = "%m%d-%H%M"


def fetch_limit(limit: int, filter: Optional[Sequence[str]]) -> Optional[int]:
    """Rows to request from the client, given a possibly-filtered request.

    A client-side ``--filter`` must run against the whole result set, so a
    filtered list fetches wide (``None`` = everything) and cuts to ``--limit``
    only after filtering.

    ``--limit 0`` returns no rows. The shared ``apply_limit`` helper treats a
    non-positive limit as "no limit"; this CLI deliberately does not, because
    ``--limit 0`` silently meaning "everything" is the more surprising reading.

    Raises:
        typer.BadParameter: for a negative limit, which would otherwise slice
            from the end of the result set and return a nonsensical subset.
    """
    if limit < 0:
        raise typer.BadParameter("--limit must be zero or greater")
    return None if filter else limit


def apply_row_filters(
    items: List[Dict[str, Any]],
    filter: Optional[Sequence[str]],
) -> List[Dict[str, Any]]:
    """Apply ``--filter`` with the rows' own field set as the allowlist.

    The shared filter module documents ``allowed_fields`` as the guard against
    a false negative: without it, a typo'd or wrong-case field name silently
    matches nothing and reads as "no rows" instead of "that field is not
    filterable". The allowlist is the union of the rows' own keys, so it always
    describes exactly what this command exposes. Values keep exact ``eq``
    semantics; use ``like``/``ilike``/``contains`` for case-insensitive
    matching.
    """
    if not filter or not items:
        return items
    allowed = set().union(*(item.keys() for item in items))
    if not allowed:
        return items
    return apply_filters(items, filter, allowed_fields=sorted(allowed))


def select_properties(
    items: List[Dict[str, Any]],
    properties: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Project each row to the comma-separated fields named by ``--properties``.

    Uses the shared projection so dot notation (``raw.id``) works and a
    requested-but-empty field is emitted as an explicit null rather than
    dropped. When no requested name resolves on any row, that is a caller
    error, not an empty result.

    Raises:
        typer.BadParameter: when none of the requested fields exist on the
            result set.
    """
    if not properties or not items:
        return items
    names = [name.strip() for name in properties.split(",") if name.strip()]
    if not names:
        return items
    if not any(
        get_nested_value(item, name) is not None for item in items for name in names
    ):
        available = ", ".join(sorted(set().union(*(item.keys() for item in items))))
        raise typer.BadParameter(
            f"--properties matched no field on this result: {', '.join(names)}. "
            f"Available fields: {available}"
        )
    return apply_properties_filter(items, properties)


def add_time(
    items: List[Dict[str, Any]],
    source: str,
    target: str,
    format: str = TABLE_TIME_FORMAT,
) -> None:
    """Add a local-time display column derived from an ISO timestamp field."""
    for item in items:
        item[target] = format_local_time(item.get(source, "") or "", format)


def blank_none(items: List[Dict[str, Any]], *fields: str) -> None:
    """Replace None with an empty string so table cells render clean."""
    for item in items:
        for field in fields:
            item[field] = item.get(field) or ""


def render_table(
    items: List[Dict[str, Any]],
    lean: Sequence[tuple],
    extra: Sequence[tuple] = (),
    wide: bool = False,
) -> None:
    """Print a table with a readable default and a full ``--wide`` variant."""
    pairs = list(lean) + (list(extra) if wide else [])
    print_table(
        items,
        [column for column, _header in pairs],
        [header for _column, header in pairs],
        max_columns=0,
    )


def truncate_value(value: Any, max_length: int = 50) -> str:
    """Render any value as a single-line string bounded to ``max_length``."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, separators=(",", ":"), default=str)
    else:
        text = str(value)
    text = text.replace("\n", " ").replace("\r", "")
    if len(text) > max_length:
        return text[: max_length - 3] + "..."
    return text


def field_value_table(pairs: Sequence[tuple]) -> None:
    """Print a two-column Field/Value table for a single record."""
    rows = [{"field": label, "value": truncate_value(value, 2000)} for label, value in pairs]
    print_table(rows, ["field", "value"], ["Field", "Value"])
