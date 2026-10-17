"""Presentation helpers shared by the list commands.

Each command applies `--filter` itself with the shared `apply_filters`, so the
filtering stays visible at the command site. This module owns only what is
presentational: `--properties` selection and table column formatting.
"""
from typing import Any, Dict, List, Optional, Sequence

from cli_tools_shared.output import print_table

from ..parsers import bounded_text, format_local_time

# Table timestamps carry the date because sessions are queried across days.
TABLE_TIME_FORMAT = "%m-%d %H:%M"

# A client-side --filter must run against the whole result set, so a filtered
# list fetches wide and applies --limit only after filtering. Without this,
# `--limit 2 --filter X` returns fewer than 2 rows whenever the first 2 rows do
# not match.
UNBOUNDED = 100_000


def to_items(rows: Sequence[Any]) -> List[Dict[str, Any]]:
    """Convert model rows to plain dicts for filtering and output."""
    return [row.model_dump() for row in rows]


def normalize_limit(limit: int) -> int:
    """Clamp a requested row limit to a non-negative count.

    A negative `--limit` must never widen a result. Slicing with a negative
    bound silently drops rows off the END of the list instead
    (`rows[:-1]` keeps nearly everything), so every limit is normalized here,
    once, before it reaches a fetch or a slice.
    """
    return max(0, int(limit))


def fetch_limit(limit: int, filter: object) -> int:
    """Rows to request from the client, given a possibly-filtered request."""
    normalized = normalize_limit(limit)
    if normalized == 0:
        return 0
    return UNBOUNDED if filter else normalized


def bound_rows(items: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """Apply `--limit` to an already-filtered row list."""
    return items[: normalize_limit(limit)]


def select_properties(
    items: List[Dict[str, Any]], properties: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Reduce each row to the comma-separated fields named by `--properties`."""
    if not properties:
        return items
    wanted = {name.strip() for name in properties.split(",") if name.strip()}
    return [{key: value for key, value in item.items() if key in wanted} for item in items]


def add_time(
    items: List[Dict[str, Any]], source: str, target: str, format: str = TABLE_TIME_FORMAT
) -> None:
    """Add a local-time display column derived from an ISO field."""
    for item in items:
        item[target] = format_local_time(item.get(source) or "", format)


# Text columns are already bounded by --max-chars, but a 200-character cell
# wraps a table into unreadable ribbons, so table mode tightens them further.
TABLE_CELL_CHARS = 40


def blank_none(items: List[Dict[str, Any]], *fields: str) -> None:
    """Replace None with an empty string so table cells render clean."""
    for item in items:
        for field in fields:
            item[field] = item.get(field) or ""


def truncate_cells(
    items: List[Dict[str, Any]], *fields: str, max_length: int = TABLE_CELL_CHARS
) -> None:
    """Shorten free-text columns so a table stays one line per row."""
    for item in items:
        for field in fields:
            value = item.get(field)
            if isinstance(value, str):
                item[field] = bounded_text(value, max_length)


def join_lists(items: List[Dict[str, Any]], *fields: str) -> None:
    """Render list-valued fields as comma-separated text for table output."""
    for item in items:
        for field in fields:
            value = item.get(field)
            if isinstance(value, list):
                item[field] = ", ".join(str(entry) for entry in value)


def add_tokens(items: List[Dict[str, Any]]) -> None:
    """Add thousands-separated token columns, blank when zero."""
    columns = {
        "in_tok": "input_tokens",
        "out_tok": "output_tokens",
        "cache_read": "cache_read_tokens",
        "reasoning": "reasoning_tokens",
        "effective": "effective_tokens",
    }
    for item in items:
        for target, source in columns.items():
            value = item.get(source) or 0
            item[target] = f"{value:,}" if value else ""


def render_table(
    items: List[Dict[str, Any]],
    lean: Sequence[tuple],
    extra: Sequence[tuple] = (),
    wide: bool = False,
) -> None:
    """Print a table with a readable default and a full `--wide` variant."""
    pairs = list(lean) + (list(extra) if wide else [])
    print_table(
        items,
        [column for column, _ in pairs],
        [header for _, header in pairs],
        max_columns=0,
    )


def field_rows(record: Dict[str, Any], order: Sequence[tuple]) -> List[Dict[str, str]]:
    """Build the Field/Value rows a `get --table` view prints."""
    rows = []
    for key, label in order:
        value = record.get(key)
        if isinstance(value, list):
            value = ", ".join(str(entry) for entry in value)
        rows.append({"field": label, "value": "" if value is None else str(value)})
    return rows


def print_record(record: Dict[str, Any], order: Sequence[tuple]) -> None:
    """Print one record as a Field/Value table."""
    print_table(field_rows(record, order), ["field", "value"], ["Field", "Value"])
