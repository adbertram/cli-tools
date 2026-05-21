"""Maps commands for MindMeister CLI."""
import typer
from typing import Optional, List

from pydantic import BaseModel

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_success, print_error, handle_error


app = typer.Typer(help="Manage MindMeister mind maps", no_args_is_help=True)


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
def maps_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of maps to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List all mind maps.

    Examples:
        mindmeister maps list
        mindmeister maps list --table
        mindmeister maps list --limit 10
        mindmeister maps list --properties "id,title,modified"
    """
    try:
        client = get_client()
        maps = client.list_maps(limit=limit, filters=filter)
        maps_dicts = [m.model_dump() if hasattr(m, 'model_dump') else m for m in maps]

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            maps_dicts = extract_fields(maps_dicts, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(maps_dicts, fields, fields)
            else:
                # Default table columns with node count hint
                print_table(
                    maps_dicts,
                    ["id", "title", "modified", "revision"],
                    ["ID", "Title", "Modified", "Rev"],
                )
        else:
            print_json(maps_dicts)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def maps_get(
    map_id: str = typer.Argument(..., help="The map ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Get a map with full structure including all ideas/nodes.

    Examples:
        mindmeister maps get 123456
        mindmeister maps get 123456 --table
        mindmeister maps get 123456 --properties "id,title,node_count"
    """
    try:
        client = get_client()
        map_detail = client.get_map(map_id)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            map_detail = extract_fields([map_detail], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([map_detail], fields, fields)
            else:
                # Convert model to key-value table
                map_dict = model_to_dict(map_detail)
                # Show summary without full ideas array
                summary_fields = ["id", "title", "revision", "description", "created", "modified", "owner", "node_count"]
                rows = [{"field": k, "value": str(map_dict.get(k, ""))} for k in summary_fields if map_dict.get(k) is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(map_detail)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def maps_create(
    title: Optional[str] = typer.Option(None, "--title", "-T", help="Title for the new map"),
    json_file: Optional[str] = typer.Option(None, "--json-file", "-j", help="JSON file with node structure"),
):
    """
    Create a new mind map.

    Create an empty map with --title, or create a structured map with nodes
    and notes using --json-file.

    JSON file format - a list containing the root node:
    [
      {
        "title": "Root Topic",
        "note": "Description of the root node",
        "children": [
          {
            "title": "Branch 1",
            "note": "What this branch covers",
            "children": [
              {"title": "Leaf Node", "note": "Leaf description"}
            ]
          },
          {"title": "Branch 2", "note": "Another branch"}
        ]
      }
    ]

    Examples:
        mindmeister maps create --title "My New Map"
        mindmeister maps create -T "Project Planning"
        mindmeister maps create --json-file my_mindmap.json
    """
    import json
    import os

    try:
        if json_file:
            # Create from JSON file with node structure
            if not os.path.exists(json_file):
                print_error(f"File not found: {json_file}")
                raise typer.Exit(1)

            with open(json_file, "r") as f:
                try:
                    nodes = json.load(f)
                except json.JSONDecodeError as e:
                    print_error(f"Invalid JSON: {e}")
                    raise typer.Exit(1)

            if not isinstance(nodes, list):
                print_error("JSON must be a list containing the root node")
                raise typer.Exit(1)

            if not nodes:
                print_error("JSON list is empty - must contain at least one root node")
                raise typer.Exit(1)

            client = get_client()
            new_map = client.create_annotated_map(nodes)
            print_success(f"Created map from JSON: {new_map.id}")
            print_json(new_map)

        elif title:
            # Create empty map with title
            client = get_client()
            new_map = client.create_map(title)
            print_success(f"Created map: {new_map.id}")
            print_json(new_map)

        else:
            print_error("Either --title or --json-file is required")
            raise typer.Exit(1)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def maps_update(
    map_id: str = typer.Argument(..., help="The map ID to update"),
    title: Optional[str] = typer.Option(None, "--title", "-T", help="New title"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="New description"),
):
    """
    Update map metadata (title, description).

    Examples:
        mindmeister maps update 123456 --title "Updated Title"
        mindmeister maps update 123456 --description "New description"
        mindmeister maps update 123456 -T "New Title" -d "New description"
    """
    try:
        if not title and not description:
            print_error("At least one of --title or --description is required")
            raise typer.Exit(1)

        client = get_client()
        updated_map = client.update_map(map_id, title=title, description=description)
        print_success(f"Updated map: {map_id}")
        print_json(updated_map)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("duplicate")
def maps_duplicate(
    map_id: str = typer.Argument(..., help="The map ID to duplicate"),
):
    """
    Duplicate an existing map.

    Examples:
        mindmeister maps duplicate 123456
    """
    try:
        client = get_client()
        new_map = client.duplicate_map(map_id)
        print_success(f"Duplicated map {map_id} -> {new_map.id}")
        print_json(new_map)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def maps_delete(
    map_id: str = typer.Argument(..., help="The map ID to delete"),
    force: bool = typer.Option(False, "--force", "-F", help="Skip confirmation"),
):
    """
    Delete a map.

    Examples:
        mindmeister maps delete 123456
        mindmeister maps delete 123456 --force
    """
    try:
        if not force:
            confirm = typer.confirm(f"Are you sure you want to delete map {map_id}?")
            if not confirm:
                print_error("Cancelled")
                raise typer.Exit(0)

        client = get_client()
        client.delete_map(map_id)
        print_success(f"Deleted map: {map_id}")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("export")
def maps_export(
    map_id: str = typer.Argument(..., help="The map ID to export"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get export URLs for a map in various formats.

    Examples:
        mindmeister maps export 123456
        mindmeister maps export 123456 --table
    """
    try:
        client = get_client()
        export_data = client.export_map(map_id)

        if table:
            # Convert to rows
            rows = []
            for key, value in export_data.items():
                if key not in ["stat", "content"] and value:
                    rows.append({"format": key, "url": str(value)})
            if rows:
                print_table(rows, ["format", "url"], ["Format", "URL"])
            else:
                from cli_tools_shared.output import print_info
                print_info("No export URLs available")
        else:
            print_json(export_data)

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "create": [
        "custom"
    ],
    "delete": [
        "custom"
    ],
    "duplicate": [
        "custom"
    ],
    "export": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "update": [
        "custom"
    ]
}
