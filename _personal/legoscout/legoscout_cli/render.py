"""One renderer for every command. JSON by default, a table on `--table`.

`--filter`, `--limit` and `--properties` are the compliance surface every `list`
command carries, and `--table` is the one every `get` carries. They behave the
same everywhere because they are implemented once, here.
"""
from __future__ import annotations

import json
from typing import List, Optional

import typer
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import print_error, print_info, print_json, print_table


def fields_of(properties: Optional[str]) -> Optional[List[str]]:
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None


def check_filters(filters: Optional[List[str]]) -> None:
    if not filters:
        return
    try:
        validate_filters(filters)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


def _cell(value):
    """A table cell holds text, so a nested value renders as compact JSON."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, default=str)


def _flat(row: dict) -> dict:
    return {key: _cell(value) for key, value in row.items()}


def rows(records, table, properties, columns=None, empty="No records found."):
    """Render a list of records."""
    fields = fields_of(properties)
    if fields:
        records = apply_properties_filter(records, properties)
    if not table:
        print_json(records)
        return
    if not records:
        print_info(empty)
        return
    names = fields or columns or list(records[0])
    print_table([_flat(row) for row in records], names,
                [name.replace("_", " ").title() for name in names])


def one(record, table, properties=None, empty="No record found."):
    """Render a single record: a key/value table on `--table`, else JSON."""
    if record is None:
        print_info(empty)
        raise typer.Exit(2)
    fields = fields_of(properties)
    if fields:
        record = {key: record.get(key) for key in fields}
    if not table:
        print_json(record)
        return
    print_table([{"field": key, "value": _cell(value)}
                 for key, value in record.items()],
                ["field", "value"], ["Field", "Value"])


def capped(records, limit):
    """The first `limit` records. A negative or absent limit caps nothing."""
    return records[:limit] if limit is not None and limit >= 0 else records
