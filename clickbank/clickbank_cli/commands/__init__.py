"""Shared command helpers for ClickBank CLI."""
from pydantic import BaseModel

from cli_tools_shared.output import print_json, print_table


def model_to_dict(item):
    """Convert a model or mapping to a plain dict."""
    if isinstance(item, BaseModel):
        return item.model_dump(mode="json")
    return item


def extract_field(item, field: str):
    """Extract a possibly nested field using dot notation."""
    data = model_to_dict(item)
    value = data
    for part in field.split("."):
        if isinstance(value, dict):
            value = value.get(part)
            continue
        return None
    return value


def extract_fields(items: list, fields: list[str]) -> list[dict]:
    """Extract selected fields from a list of models or dicts."""
    extracted = []
    for item in items:
        extracted.append({field: extract_field(item, field) for field in fields})
    return extracted


def parse_properties(properties: str | None) -> list[str] | None:
    """Parse the --properties option into a field list."""
    if properties is None:
        return None
    return [field.strip() for field in properties.split(",")]


def emit_rows(
    rows,
    *,
    table: bool,
    properties: str | None,
    default_columns: list[str],
    default_headers: list[str],
):
    """Render rows using the shared JSON/table output conventions."""
    fields = parse_properties(properties)
    output_rows = extract_fields(rows, fields) if fields else rows
    if table:
        columns = fields or default_columns
        headers = fields or default_headers
        print_table(output_rows, columns, headers)
        return
    print_json(output_rows)
