"""Area commands for Things CLI."""
import typer
from typing import Optional, List

from pydantic import BaseModel

from cli_tools_shared.filters import apply_filters
from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error


app = typer.Typer(help="Manage areas", no_args_is_help=True)


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
def areas_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of items"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """
    List areas.

    Examples:
        things areas list
        things areas list --table
        things areas list --properties "uuid,title"
    """
    try:
        client = get_client()
        areas = client.list_areas(limit=limit)

        # Apply client-side filters if provided
        if filter:
            areas_dicts = [model_to_dict(a) for a in areas]
            areas = apply_filters(areas_dicts, filter)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            areas = extract_fields(areas, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(areas, fields, fields)
            else:
                print_table(
                    areas,
                    ["uuid", "title", "visible", "index"],
                    ["UUID", "Title", "Visible", "Index"],
                )
        else:
            print_json(areas)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def areas_get(
    uuid: str = typer.Argument(..., help="The area UUID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """
    Get a specific area by UUID.

    Examples:
        things areas get UUID
        things areas get UUID --table
    """
    try:
        client = get_client()
        area = client.get_area(uuid)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            area = extract_fields([area], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([area], fields, fields)
            else:
                item_dict = model_to_dict(area)
                rows = [{"field": k, "value": str(v)} for k, v in item_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(area)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def areas_create(
    title: str = typer.Argument(..., help="Area title"),
):
    """
    Create a new area.

    Examples:
        things areas create "Work"
        things areas create "Personal"
    """
    try:
        client = get_client()
        area = client.create_area(title=title)

        from cli_tools_shared.output import print_info
        print_info(f"Created area: {area.uuid}")
        print_json(area)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def areas_delete(
    uuid: str = typer.Argument(..., help="The area UUID"),
):
    """
    Delete an area.

    Examples:
        things areas delete UUID
    """
    try:
        client = get_client()
        result = client.delete_area(uuid)

        from cli_tools_shared.output import print_info
        print_info(f"Deleted area: {result['title']}")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def areas_update(
    uuid: str = typer.Argument(..., help="The area UUID"),
    title: Optional[str] = typer.Option(None, "--title", help="New title"),
):
    """
    Update an area.

    Examples:
        things areas update UUID --title "New Title"
    """
    try:
        client = get_client()
        area = client.update_area(uuid=uuid, title=title)

        from cli_tools_shared.output import print_info
        print_info(f"Updated: {area.title}")
        print_json(area)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("search")
def areas_search(
    query: str = typer.Argument(..., help="Search query (matches title)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """
    Search areas by title.

    Examples:
        things areas search "work"
        things areas search "personal" --table
    """
    try:
        client = get_client()
        areas = client.list_areas(limit=limit)

        # Filter by title containing query (case-insensitive)
        query_lower = query.lower()
        areas = [a for a in areas if query_lower in a.title.lower()]

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            areas = extract_fields(areas, fields)

        if table:
            if areas:
                if properties:
                    columns = [f.strip() for f in properties.split(",")]
                else:
                    columns = ["uuid", "title"]
                print_table(areas, columns, columns)
            else:
                from cli_tools_shared.output import print_info
                print_info("No areas found matching the search query.")
        else:
            print_json(areas)

    except Exception as e:
        raise typer.Exit(handle_error(e))
