"""Items commands for Freshworks CLI."""

from typing import List, Optional

import typer
from pydantic import BaseModel

from cli_tools_shared.output import handle_error, print_json, print_table

from .client import get_client

COMMAND_CREDENTIALS = {
    "list": ["api_key"],
    "get": ["api_key"],
    "search": ["api_key"],
}

app = typer.Typer(help="Manage freshworks items", no_args_is_help=True)


def model_to_dict(item):
    """Convert model or dict to dict for field extraction."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def extract_field(item, field: str):
    """Extract a field value, supporting dot-notation for nested fields."""
    data = model_to_dict(item)
    value = data
    for part in field.split("."):
        if isinstance(value, dict):
            value = value.get(part)
            continue
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


@app.command("list")
def items_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of items to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include (supports dot-notation)"),
):
    """List items."""
    try:
        items = get_client().list_items(limit=limit, filters=filter)
        if properties:
            fields = [field.strip() for field in properties.split(",")]
            items = extract_fields(items, fields)

        if table:
            if properties:
                fields = [field.strip() for field in properties.split(",")]
                print_table(items, fields, fields)
            else:
                print_table(items, ["id", "name", "status"], ["ID", "Name", "Status"])
        else:
            print_json(items)
    except Exception as error:
        raise typer.Exit(handle_error(error))


@app.command("get")
def items_get(
    item_id: str = typer.Argument(..., help="The item ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include (supports dot-notation)"),
):
    """Get details for a specific item."""
    try:
        item = get_client().get_item(item_id)
        if properties:
            fields = [field.strip() for field in properties.split(",")]
            item = extract_fields([item], fields)[0]

        if table:
            if properties:
                fields = [field.strip() for field in properties.split(",")]
                print_table([item], fields, fields)
            else:
                item_dict = model_to_dict(item)
                rows = [{"field": key, "value": str(value)} for key, value in item_dict.items() if value is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(item)
    except Exception as error:
        raise typer.Exit(handle_error(error))


@app.command("search")
def items_search(
    query: str = typer.Argument(..., help="Search query (supports * wildcards)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    fields: Optional[str] = typer.Option(None, "--fields", help="Comma-separated fields to search"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include (supports dot-notation)"),
):
    """Search items with wildcard pattern matching."""
    try:
        results = get_client().search_items(query=query, limit=limit, fields=fields)
        if properties:
            selected = [field.strip() for field in properties.split(",")]
            results = extract_fields(results, selected)

        if table:
            columns = [field.strip() for field in properties.split(",")] if properties else ["id", "name", "status"]
            print_table(results, columns, columns)
        else:
            print_json(results)
    except Exception as error:
        raise typer.Exit(handle_error(error))
