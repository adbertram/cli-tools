"""Items commands for Descript CLI.

TODO: Rename this file and update commands for your specific resource.
"""
import typer
from typing import Optional, List

from pydantic import BaseModel

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error


app = typer.Typer(help="Manage descript items", no_args_is_help=True)


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


@app.command("list")
def items_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of items to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include (supports dot-notation)"),
):
    """
    List items.

    Examples:
        descript items list
        descript items list --table
        descript items list --limit 10
        descript items list --filter "status:active"
        descript items list --properties "id,name"
        descript items list --properties "id,user.name,status"
    """
    try:
        client = get_client()
        # Returns List[Item] models
        items = client.list_items(limit=limit, filters=filter)

        # Apply properties field selection with dot-notation support
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            items = extract_fields(items, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(items, fields, fields)
            else:
                # Default table columns - update for your model
                print_table(
                    items,
                    ["id", "name", "status"],
                    ["ID", "Name", "Status"],
                )
        else:
            print_json(items)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def items_get(
    item_id: str = typer.Argument(..., help="The item ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include (supports dot-notation)"),
):
    """
    Get details for a specific item.

    Examples:
        descript items get ITEM_ID
        descript items get ITEM_ID --table
        descript items get ITEM_ID --properties "id,name"
        descript items get ITEM_ID --properties "user.name,user.email"
    """
    try:
        client = get_client()
        # Returns ItemDetail model
        item = client.get_item(item_id)

        # Apply properties field selection with dot-notation support
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            item = extract_fields([item], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([item], fields, fields)
            else:
                # Convert model to key-value table
                item_dict = model_to_dict(item)
                rows = [{"field": k, "value": str(v)} for k, v in item_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(item)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("search")
def items_search(
    query: str = typer.Argument(..., help="Search query (supports * wildcards)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    fields: Optional[str] = typer.Option(None, "--fields", help="Comma-separated fields to search"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include (supports dot-notation)"),
):
    """
    Search items with wildcard pattern matching.

    Supports * wildcards for pattern matching across all string fields.

    Examples:
        descript items search "*invoice*"
        descript items search "INV-2024*"
        descript items search "*pending*" --fields "status,notes"
        descript items search "*error*" --properties "id,name,status" --table
    """
    try:
        client = get_client()

        # Get search fields if specified
        search_fields = [f.strip() for f in fields.split(",")] if fields else None

        # Search items - returns List[Item] models
        items = client.search_items(query=query, limit=limit, fields=search_fields)

        # Apply properties field selection with dot-notation support
        if properties:
            prop_fields = [f.strip() for f in properties.split(",")]
            items = extract_fields(items, prop_fields)

        if table:
            if items:
                if properties:
                    columns = [f.strip() for f in properties.split(",")]
                else:
                    columns = ["id", "name", "status"]
                print_table(items, columns, columns)
            else:
                from cli_tools_shared.output import print_info
                print_info("No items found matching the search query.")
        else:
            print_json(items)

    except Exception as e:
        raise typer.Exit(handle_error(e))
