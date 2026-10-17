"""Shared rendering for Muse commands."""

from __future__ import annotations

from typing import Optional

import typer
from cli_tools_shared.filters import apply_properties_filter
from cli_tools_shared.output import print_json, print_table


def property_fields(properties: Optional[str]) -> Optional[list[str]]:
    """Parse comma-separated output fields."""
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None


def render_rows(
    rows: list[dict],
    *,
    table: bool,
    properties: Optional[str],
    default_columns: list[str],
) -> None:
    """Render list-shaped data with standard property selection."""
    fields = property_fields(properties)
    if fields:
        rows = apply_properties_filter(rows, properties)
    if table:
        columns = fields or default_columns
        print_table(rows, columns, [column.replace("_", " ").title() for column in columns])
    else:
        print_json(rows)


def render_record(
    record: dict,
    *,
    table: bool,
    properties: Optional[str],
    default_columns: list[str],
) -> None:
    """Render one record with standard property selection."""
    fields = property_fields(properties)
    if fields:
        record = apply_properties_filter([record], properties)[0]
    if table:
        columns = fields or default_columns
        print_table([record], columns, [column.replace("_", " ").title() for column in columns])
    else:
        print_json(record)


def emit_monitor_result(result: dict) -> None:
    """Print a monitor result; timeouts remain structured and nonzero."""
    print_json(result)
    if result.get("status") == "timeout":
        raise typer.Exit(1)
