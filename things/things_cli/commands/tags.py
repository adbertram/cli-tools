"""Tag commands for Things CLI."""
import typer
from typing import Optional, List

from pydantic import BaseModel

from cli_tools_shared.filters import apply_filters
from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error


app = typer.Typer(help="Manage tags", no_args_is_help=True)


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
def tags_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of items"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """
    List tags.

    Examples:
        things tags list
        things tags list --table
        things tags list --properties "uuid,title,shortcut"
    """
    try:
        client = get_client()
        tags = client.list_tags(limit=limit)

        # Apply client-side filters if provided
        if filter:
            tags_dicts = [model_to_dict(t) for t in tags]
            tags = apply_filters(tags_dicts, filter)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            tags = extract_fields(tags, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(tags, fields, fields)
            else:
                print_table(
                    tags,
                    ["uuid", "title", "shortcut", "parent_uuid"],
                    ["UUID", "Title", "Shortcut", "Parent UUID"],
                )
        else:
            print_json(tags)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def tags_get(
    uuid: str = typer.Argument(..., help="The tag UUID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """
    Get a specific tag by UUID.

    Examples:
        things tags get UUID
        things tags get UUID --table
    """
    try:
        client = get_client()
        tag = client.get_tag(uuid)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            tag = extract_fields([tag], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([tag], fields, fields)
            else:
                item_dict = model_to_dict(tag)
                rows = [{"field": k, "value": str(v)} for k, v in item_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(tag)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("search")
def tags_search(
    query: str = typer.Argument(..., help="Search query (matches title)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """
    Search tags by title.

    Examples:
        things tags search "work"
        things tags search "urgent" --table
    """
    try:
        client = get_client()
        tags = client.list_tags(limit=limit)

        # Filter by title containing query (case-insensitive)
        query_lower = query.lower()
        tags = [t for t in tags if query_lower in t.title.lower()]

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            tags = extract_fields(tags, fields)

        if table:
            if tags:
                if properties:
                    columns = [f.strip() for f in properties.split(",")]
                else:
                    columns = ["uuid", "title", "shortcut"]
                print_table(tags, columns, columns)
            else:
                from cli_tools_shared.output import print_info
                print_info("No tags found matching the search query.")
        else:
            print_json(tags)

    except Exception as e:
        raise typer.Exit(handle_error(e))
