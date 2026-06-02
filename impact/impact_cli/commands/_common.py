"""Shared command helpers."""
from typing import Any, Optional
import json
import sys

from pydantic import BaseModel

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import print_json, print_table


FIELD_ALIASES = {
    "id": ["id", "Id", "ID", "CampaignId", "UserId", "InvoiceId", "Uri"],
    "name": [
        "name",
        "Name",
        "CampaignName",
        "AdvertiserName",
        "CompanyName",
        "DisplayName",
        "FirstName",
        "BeneficiaryAccountName",
        "RecipientName",
        "PaymentMethod",
        "Status",
        "Type",
        "Title",
        "Url",
        "Website",
    ],
}


def model_to_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, BaseModel):
        return item.model_dump(mode="json")
    if isinstance(item, dict):
        return item
    raise ClientError(f"Expected object output, got {type(item).__name__}")


def extract_field(item: Any, field: str) -> Any:
    value: Any = model_to_dict(item)
    if "." not in field and field in FIELD_ALIASES:
        for alias in FIELD_ALIASES[field]:
            if alias in value:
                return value[alias]
        raise ClientError(f"Field path '{field}' was not found")

    for part in field.split("."):
        if not isinstance(value, dict):
            raise ClientError(f"Field path '{field}' cannot descend into non-object value")
        if part not in value:
            raise ClientError(f"Field path '{field}' was not found")
        value = value[part]
    return value


def extract_fields(items: list[Any], fields: list[str]) -> list[dict[str, Any]]:
    return [{field: extract_field(item, field) for field in fields} for item in items]


def parse_properties(properties: str) -> list[str]:
    fields = [field.strip() for field in properties.split(",")]
    if not all(fields):
        raise ClientError("Properties must be a comma-separated list of field names")
    return fields


def read_json_body(json_file: Optional[str]) -> dict[str, Any]:
    if json_file:
        with open(json_file, "r", encoding="utf-8") as file:
            body = json.load(file)
    else:
        body = json.load(sys.stdin)
    if not isinstance(body, dict):
        raise ClientError("JSON body must be an object")
    return body


def output_list(
    items: list[Any],
    table: bool,
    properties: Optional[str],
    default_columns: list[str],
    default_headers: list[str],
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


def apply_cli_filters(items: list[Any], filters: Optional[list[str]]) -> list[Any]:
    if not filters:
        return items
    filtered = apply_filters([model_to_dict(item) for item in items], filters)
    return filtered


def output_item(item: Any, table: bool) -> None:
    if table:
        data = model_to_dict(item)
        rows = [{"field": key, "value": value} for key, value in data.items()]
        print_table(rows, ["field", "value"], ["Field", "Value"])
    else:
        print_json(item)


def output_download(download: Any, table: bool) -> None:
    output_item(download, table)
