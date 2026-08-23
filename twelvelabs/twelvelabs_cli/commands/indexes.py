"""Indexes commands for TwelveLabs CLI."""
import typer
from typing import Optional, List

from pydantic import BaseModel

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_success, print_info, handle_error
from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
from cli_tools_shared import FilterMap


app = typer.Typer(help="Manage TwelveLabs indexes", no_args_is_help=True)


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
def indexes_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of indexes to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List all indexes.

    Examples:
        twelvelabs indexes list
        twelvelabs indexes list --table
        twelvelabs indexes list --limit 10
        twelvelabs indexes list --filter "index_name:contains:course"
        twelvelabs indexes list --properties "id,index_name,video_count"
    """
    try:
        # Validate filters if provided
        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as e:
                from cli_tools_shared.output import print_error
                print_error(f"Invalid filter: {e}")
                raise typer.Exit(1)

        client = get_client()
        indexes = client.list_indexes(limit=limit)

        # Apply client-side filters (TwelveLabs API doesn't support server-side filtering)
        if filter:
            indexes = apply_filters(indexes, filter)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            indexes = extract_fields(indexes, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(indexes, fields, fields)
            else:
                print_table(
                    indexes,
                    ["id", "index_name", "video_count"],
                    ["ID", "Name", "Videos"],
                )
        else:
            print_json(indexes)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def indexes_get(
    index_id: str = typer.Argument(..., help="The index ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Get details for a specific index.

    Examples:
        twelvelabs indexes get INDEX_ID
        twelvelabs indexes get INDEX_ID --table
        twelvelabs indexes get INDEX_ID --properties "id,index_name"
    """
    try:
        client = get_client()
        index = client.get_index(index_id)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            index = extract_fields([index], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([index], fields, fields)
            else:
                item_dict = model_to_dict(index)
                rows = [{"field": k, "value": str(v)} for k, v in item_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(index)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def indexes_create(
    name: str = typer.Argument(..., help="Name for the new index"),
    engine: str = typer.Option("pegasus1.5", "--engine", "-e", help="Engine to use (default: pegasus1.5)"),
):
    """
    Create a new index.

    Examples:
        twelvelabs indexes create my-course-index
        twelvelabs indexes create ai-102-nlp --engine pegasus1.5
    """
    try:
        client = get_client()
        engines = [{"engine_name": engine, "engine_options": ["visual", "audio"]}]
        index = client.create_index(name=name, engines=engines)
        print_success(f"Index '{name}' created successfully")
        print_json(index)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def indexes_delete(
    index_id: str = typer.Argument(..., help="The index ID to delete"),
    force: bool = typer.Option(False, "--force", "-F", help="Skip confirmation"),
):
    """
    Delete an index and all its videos.

    Examples:
        twelvelabs indexes delete INDEX_ID
        twelvelabs indexes delete INDEX_ID --force
    """
    try:
        if not force:
            confirm = typer.confirm(f"Are you sure you want to delete index {index_id}? This will delete all videos in the index.")
            if not confirm:
                print_info("Deletion cancelled")
                raise typer.Exit(0)

        client = get_client()
        client.delete_index(index_id)
        print_success(f"Index {index_id} deleted successfully")

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "create": [
        "custom"
    ],
    "delete": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ]
}
