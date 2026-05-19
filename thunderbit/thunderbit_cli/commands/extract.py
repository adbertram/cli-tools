"""Thunderbit structured extraction commands."""
COMMAND_CREDENTIALS = {
    "run": ["api_key"],
}

import json
from typing import Optional

import typer
from pydantic import BaseModel

from ..client import get_client
from cli_tools_shared.output import handle_error, print_json, print_table


app = typer.Typer(help="Extract structured JSON from web pages", no_args_is_help=True)


def model_to_dict(item):
    """Convert model or dict to dict for field extraction."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def extract_field(item, field: str):
    """Extract a field value, supporting dot-notation for nested fields."""
    data = model_to_dict(item)
    parts = field.split(".")
    value = data
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def extract_fields(items: list, fields: list) -> list:
    """Extract specified fields from items, supporting dot-notation."""
    result = []
    for item in items:
        extracted = {}
        for field in fields:
            extracted[field] = extract_field(item, field)
        result.append(extracted)
    return result


@app.command("run")
def extract_run(
    url: str = typer.Argument(..., help="Absolute URL to extract from"),
    schema_file: str = typer.Option(..., "--schema-file", help="Path to a JSON Schema file"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include (supports dot-notation)"),
):
    """
    Run Thunderbit's structured extraction endpoint.

    Examples:
        thunderbit extract run https://example.com/product --schema-file product-schema.json
        thunderbit extract run https://example.com/product --schema-file product-schema.json --table
    """
    try:
        with open(schema_file, "r", encoding="utf-8") as handle:
            schema = json.load(handle)

        client = get_client()
        item = client.extract_url(url, schema=schema)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            item = extract_fields([item], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([item], fields, fields)
            else:
                print_table([item], ["id", "name", "output_kind"], ["ID", "Name", "Output Kind"])
        else:
            print_json(item)

    except Exception as e:
        raise typer.Exit(handle_error(e))
