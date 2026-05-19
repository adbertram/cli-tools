"""Shared command helpers for the Awin CLI."""
from typing import Any, Optional

from pydantic import BaseModel

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import print_json, print_table


def model_to_dict(item: Any) -> dict:
    if isinstance(item, BaseModel):
        return item.model_dump(mode="json")
    if isinstance(item, dict):
        return item
    raise ClientError(f"Expected object output, got {type(item).__name__}")


def extract_field(item: Any, field: str) -> Any:
    data = model_to_dict(item)
    value: Any = data
    for part in field.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def extract_fields(items: list, fields: list) -> list:
    return [{field: extract_field(item, field) for field in fields} for item in items]


def parse_properties(properties: str) -> list:
    fields = [field.strip() for field in properties.split(",")]
    if not all(fields):
        raise ClientError("Properties must be a comma-separated list of field names")
    return fields


def output_list(
    items: list,
    table: bool,
    properties: Optional[str],
    default_columns: list,
    default_headers: list,
) -> None:
    if properties:
        fields = parse_properties(properties)
        items = extract_fields(items, fields)
    if table:
        if properties:
            fields = parse_properties(properties)
            print_table(items, fields, fields)
        else:
            rows = extract_fields(items, default_columns)
            print_table(rows, default_columns, default_headers)
    else:
        print_json(items)


def apply_cli_filters(items: list, filters: Optional[list]) -> list:
    if not filters:
        return items
    return apply_filters([model_to_dict(item) for item in items], filters)


def output_item(item: Any, table: bool) -> None:
    if table:
        data = model_to_dict(item)
        rows = [{"field": key, "value": value} for key, value in data.items()]
        print_table(rows, ["field", "value"], ["Field", "Value"])
    else:
        print_json(item)
