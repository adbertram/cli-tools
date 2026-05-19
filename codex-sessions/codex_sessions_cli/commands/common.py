"""Shared command output helpers."""
from typing import Iterable, List, Optional

import typer
from pydantic import BaseModel

from cli_tools_shared.filters import FilterValidationError, apply_filters, validate_filters
from cli_tools_shared.output import handle_error, print_error, print_json, print_table


def model_to_dict(item):
    if isinstance(item, BaseModel):
        return item.model_dump(mode="json")
    return item


def extract_field(item: dict, field: str):
    value = item
    for part in field.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def apply_properties(items: List[dict], properties: Optional[str]) -> List[dict]:
    if properties is None:
        return items
    fields = [field.strip() for field in properties.split(",")]
    return [
        {field: extract_field(item, field) for field in fields}
        for item in items
    ]


def emit_list(
    items: Iterable,
    table: bool,
    columns: List[str],
    headers: List[str],
    filter: Optional[List[str]] = None,
    properties: Optional[str] = None,
) -> None:
    try:
        data = [model_to_dict(item) for item in items]
        if filter:
            validate_filters(filter)
            data = apply_filters(data, filter)
        data = apply_properties(data, properties)
        if table:
            selected_columns = [field.strip() for field in properties.split(",")] if properties else columns
            selected_headers = selected_columns if properties else headers
            print_table(data, selected_columns, selected_headers)
        else:
            print_json(data)
    except FilterValidationError as error:
        print_error(str(error))
        raise typer.Exit(1)
    except Exception as error:
        raise typer.Exit(handle_error(error))


def emit_one(item, table: bool, columns: Optional[List[str]] = None, properties: Optional[str] = None) -> None:
    try:
        data = model_to_dict(item)
        if properties:
            data = apply_properties([data], properties)[0]
        if table:
            table_columns = [field.strip() for field in properties.split(",")] if properties else columns
            if table_columns is None:
                table_columns = list(data.keys())
            print_table([data], table_columns, table_columns)
        else:
            print_json(data)
    except Exception as error:
        raise typer.Exit(handle_error(error))
