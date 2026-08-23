"""Shared rendering helpers for Upwork command groups.

Both the ``profile`` and ``jobs`` groups render list/record output as JSON by
default with an optional ``--table`` view and ``--properties`` projection. This
module owns that logic once. Parameters preserve each group's existing output
contract (profile keeps its empty-table message and its JSON-on-properties
record behavior; jobs uses a field/value record table).
"""

from __future__ import annotations

from typing import Any, Optional

from cli_tools_shared.filters import apply_properties_filter
from cli_tools_shared.output import print_info, print_json, print_table


def property_fields(properties: Optional[str]) -> Optional[list[str]]:
    """Return normalized field names from a comma-separated properties value."""
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None


def headers_for(columns: list[str]) -> list[str]:
    """Build human-readable table headers from field names."""
    return [column.replace("_", " ").replace(".", " ").title() for column in columns]


def render_list(
    rows: list[dict[str, Any]],
    *,
    table: bool,
    properties: Optional[str],
    default_columns: list[str],
    empty: Optional[str] = None,
) -> None:
    """Render list output as JSON by default or a compact table on request.

    Args:
        rows: Records to render.
        table: Render as a table when true, otherwise JSON.
        properties: Optional comma-separated projection.
        default_columns: Table columns used when no projection is given.
        empty: Optional info message printed instead of an empty table.
    """
    selected = property_fields(properties)
    if selected:
        rows = apply_properties_filter(rows, properties)
    if not table:
        print_json(rows)
        return
    if not rows and empty is not None:
        print_info(empty)
        return
    columns = selected or default_columns
    print_table(rows, columns, headers_for(columns))


def render_record(
    record: dict[str, Any],
    *,
    table: bool,
    properties: Optional[str],
    key_value_columns: tuple[str, str] = ("field", "value"),
    json_on_properties: bool = False,
) -> None:
    """Render one record as JSON by default or a table on request.

    Args:
        record: Record to render.
        table: Render as a table when true, otherwise JSON.
        properties: Optional comma-separated projection.
        key_value_columns: Column names for the key/value table form.
        json_on_properties: When true, a projected record is printed as JSON
            even in table mode (preserves the profile group's behavior).
    """
    selected = property_fields(properties)
    if selected:
        filtered = apply_properties_filter([record], properties)
        record = filtered[0] if filtered else {}
        if json_on_properties or not table:
            print_json(record)
            return
    if not table:
        print_json(record)
        return
    key_col, value_col = key_value_columns
    rows = [{key_col: key, value_col: value} for key, value in record.items()]
    print_table(rows, [key_col, value_col], headers_for([key_col, value_col]))
