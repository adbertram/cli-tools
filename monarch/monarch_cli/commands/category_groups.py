"""Category groups commands for Monarch CLI."""
import typer
from typing import Optional, List

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError

app = typer.Typer(help="Manage category groups")

COMMAND_CREDENTIALS = {
    "get": [
        "username_password"
    ],
    "list": [
        "username_password"
    ]
}


def _apply_properties_filter(items: List[dict], properties: str) -> List[dict]:
    """Filter items to include only specified properties."""
    if not properties:
        return items
    props = [p.strip() for p in properties.split(",")]
    return [{k: v for k, v in item.items() if k in props} for item in items]


def _extract_groups(data: dict) -> list:
    """Extract category groups from API response."""
    groups = data.get("categoryGroups", [])
    return [
        {
            "id": g.get("id", ""),
            "name": g.get("name", ""),
            "type": g.get("type", ""),
        }
        for g in groups
    ]


@app.command("list")
def category_groups_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum category groups to return"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., type:expense, name:ilike:%income%)",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """
    List all category groups.

    Examples:
        monarch category-groups list
        monarch category-groups list --table
        monarch category-groups list --filter "type:expense"
        monarch category-groups list --filter "name:ilike:%food%"
    """
    try:
        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as e:
                typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(1)

        client = get_client()
        data = client.get_category_groups()
        groups = _extract_groups(data)[:limit]

        if filter:
            groups = apply_filters(groups, filter)

        if properties:
            groups = _apply_properties_filter(groups, properties)

        if table:
            cols = list(groups[0].keys()) if groups else ["id", "name", "type"]
            print_table(groups, cols, [c.title() for c in cols])
        else:
            print_json(groups)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def category_groups_get(
    group_id: str = typer.Argument(..., help="Category group ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for a specific category group.

    Examples:
        monarch category-groups get 12345678
        monarch category-groups get 12345678 --table
    """
    try:
        client = get_client()
        data = client.get_category_groups()
        groups = _extract_groups(data)

        group = None
        for g in groups:
            if str(g.get("id")) == str(group_id):
                group = g
                break

        if not group:
            typer.echo(f"Error: Category group with ID '{group_id}' not found", err=True)
            raise typer.Exit(1)

        if table:
            rows = [{"field": k, "value": str(v)} for k, v in group.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(group)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))
