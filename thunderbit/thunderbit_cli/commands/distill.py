"""Thunderbit Markdown distillation commands."""
COMMAND_CREDENTIALS = {
    "run": ["api_key"],
}

import typer
from typing import Optional

from pydantic import BaseModel

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error


app = typer.Typer(help="Distill web pages into Markdown", no_args_is_help=True)


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
            value = extract_field(item, field)
            extracted[field] = value
        result.append(extracted)
    return result


@app.command("run")
def distill_run(
    url: str = typer.Argument(..., help="Absolute URL to distill"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include (supports dot-notation)"),
):
    """
    Run Thunderbit's Markdown distillation endpoint.

    Examples:
        thunderbit distill run https://example.com/article
        thunderbit distill run https://example.com/article --table
        thunderbit distill run https://example.com/article --properties "id,output_kind"
    """
    try:
        client = get_client()
        item = client.distill_url(url)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            item = extract_fields([item], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([item], fields, fields)
            else:
                print_table(
                    [item],
                    ["id", "name", "output_kind"],
                    ["ID", "Name", "Output Kind"],
                )
        else:
            print_json(item)

    except Exception as e:
        raise typer.Exit(handle_error(e))
