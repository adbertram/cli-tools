"""Command output helpers."""
from typing import Any, List, Optional

from pydantic import BaseModel

from cli_tools_shared.filters import apply_properties_filter
from cli_tools_shared.output import print_json, print_table

from ..parsers import format_local_time


TIMESTAMP_FIELDS = {
    "create_time",
    "create_time_ns",
    "expiry_timestamp_ms",
    "t",
    "update_time",
}


def item_to_dict(item: Any) -> dict:
    """Convert a model or mapping to a plain dict."""
    if isinstance(item, BaseModel):
        return item.model_dump(mode="json")
    return dict(item)


def property_names(properties: Optional[str]) -> List[str]:
    """Parse comma-separated property names."""
    if not properties:
        return []
    return [name.strip() for name in properties.split(",") if name.strip()]


def select_properties(data: Any, properties: Optional[str]) -> Any:
    """Select output properties from a list or single item."""
    if not properties:
        return data

    if isinstance(data, list):
        return apply_properties_filter([item_to_dict(item) for item in data], properties)
    rows = apply_properties_filter([item_to_dict(data)], properties)
    return rows[0] if rows else {}


def format_table_rows(rows: List[dict], columns: List[str]) -> List[dict]:
    """Format timestamp columns for table output."""
    formatted = []
    for row in rows:
        table_row = dict(row)
        for column in columns:
            if column in TIMESTAMP_FIELDS and table_row.get(column) is not None:
                table_row[column] = format_local_time(table_row[column])
        formatted.append(table_row)
    return formatted


def emit(
    data: Any,
    *,
    table: bool,
    columns: List[str],
    properties: Optional[str] = None,
):
    """Print JSON or table output."""
    selected = select_properties(data, properties)
    if table:
        rows = selected if isinstance(selected, list) else [selected]
        table_columns = property_names(properties) or columns
        rows = format_table_rows([item_to_dict(row) for row in rows], table_columns)
        print_table(rows, table_columns, table_columns)
    else:
        print_json(selected)
