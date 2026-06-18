"""Shared rendering helpers for WP Engine commands."""

from __future__ import annotations

from typing import Any, Optional

from cli_tools_shared.filters import apply_properties_filter
from cli_tools_shared.output import print_json, print_table


def property_fields(properties: Optional[str]) -> list[str]:
    """Return normalized field names from a comma-separated properties value."""
    if not properties:
        return []
    return [field.strip() for field in properties.split(",") if field.strip()]


def project_rows(rows: list[dict[str, Any]], properties: Optional[str]) -> list[dict[str, Any]]:
    """Apply explicit field projection while preserving full rows by default."""
    if not properties:
        return rows
    return apply_properties_filter(rows, properties)


def project_record(record: dict[str, Any], properties: Optional[str]) -> dict[str, Any]:
    """Apply explicit field projection to one record."""
    if not properties:
        return record
    return apply_properties_filter([record], properties)[0]


def headers_for(columns: list[str]) -> list[str]:
    """Build human-readable table headers from field names."""
    return [column.replace("_", " ").replace(".", " ").title() for column in columns]


def render_list(
    rows: list[dict[str, Any]],
    *,
    table: bool,
    properties: Optional[str],
    default_columns: list[str],
) -> None:
    """Render list output as JSON by default or a compact table on request."""
    output = project_rows(rows, properties)
    if table:
        columns = property_fields(properties) or default_columns
        print_table(output, columns, headers_for(columns))
        return
    print_json(output)


def render_record(
    record: dict[str, Any],
    *,
    table: bool,
    properties: Optional[str],
    default_columns: Optional[list[str]] = None,
) -> None:
    """Render one record as JSON by default or a table on request."""
    output = project_record(record, properties)
    if table:
        columns = property_fields(properties)
        if columns:
            print_table([output], columns, headers_for(columns))
            return
        if default_columns:
            print_table([output], default_columns, headers_for(default_columns))
            return
        rows = [{"field": key, "value": value} for key, value in output.items()]
        print_table(rows, ["field", "value"], ["Field", "Value"])
        return
    print_json(output)
