"""Shared display helpers for Bricklink CLI commands."""
from datetime import datetime
import re
from typing import Optional

from cli_tools_shared.output import print_json, print_table


ISO_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:")
TIME_FIELD_TOKENS = ("date", "time", "timestamp")


def _is_timestamp_field(field: str) -> bool:
    field_name = field.lower()
    return any(token in field_name for token in TIME_FIELD_TOKENS)


def _format_table_value(field: str, value):
    if isinstance(value, str) and _is_timestamp_field(field) and ISO_TIMESTAMP_RE.match(value):
        timestamp = value.replace("Z", "+00:00") if value.endswith("Z") else value
        return datetime.fromisoformat(timestamp).astimezone().strftime("%b %d %H:%M")
    return value


def _as_dict(item):
    if isinstance(item, dict):
        return item
    return dict(item)


def _format_table_rows(data, columns: list):
    rows = []
    for item in data:
        row = dict(_as_dict(item))
        for column in columns:
            if column in row:
                row[column] = _format_table_value(column, row[column])
        rows.append(row)
    return rows


def print_detail(item, table: bool = False):
    """Display a single item as JSON or a key-value table."""
    if table:
        d = _as_dict(item)
        rows = [
            {"field": k, "value": str(_format_table_value(k, v))}
            for k, v in d.items()
            if v is not None
        ]
        print_table(rows, ["field", "value"], ["Field", "Value"])
    else:
        print_json(item)


def print_list(data, table: bool, properties: Optional[str],
               default_columns: list, default_headers: list):
    """Display a list as JSON or table with optional property column selection."""
    if table:
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            print_table(_format_table_rows(data, fields), fields, fields)
        else:
            print_table(_format_table_rows(data, default_columns), default_columns, default_headers)
    else:
        print_json(data)
