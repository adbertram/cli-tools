"""Categories commands for Monarch CLI."""
import typer
from typing import Optional, List

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_error, handle_error
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError

app = typer.Typer(help="Manage transaction categories")

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


@app.command("list")
def categories_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum categories to return"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., group:Income, name:like:%food%)",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """
    List all transaction categories.

    Filter Examples:
        monarch categories list --filter "group:Income"
        monarch categories list --filter "name:like:%food%"
    """
    try:
        # Validate filters early
        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as e:
                typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(1)

        client = get_client()
        data = client.get_categories()

        categories = data.get("categories", [])[:limit]

        # Normalize to dicts with id field
        rows = []
        for c in categories:
            rows.append({
                "id": c.get("id", ""),
                "name": c.get("name", ""),
                "group": c.get("group", {}).get("name", "") if c.get("group") else "",
                "icon": c.get("icon", ""),
            })

        # Apply client-side filters
        if filter:
            rows = apply_filters(rows, filter)

        # Apply properties filter
        if properties:
            rows = _apply_properties_filter(rows, properties)

        if table:
            cols = list(rows[0].keys()) if rows else ["id", "name", "group", "icon"]
            print_table(rows, cols, [c.title() for c in cols])
        else:
            print_json(rows)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def categories_get(
    category_id: str = typer.Argument(..., help="Category ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get details for a specific category."""
    try:
        client = get_client()
        data = client.get_categories()
        categories = data.get("categories", [])

        category = None
        for c in categories:
            if str(c.get("id", "")) == str(category_id):
                category = {
                    "id": c.get("id", ""),
                    "name": c.get("name", ""),
                    "group": c.get("group", {}).get("name", "") if c.get("group") else "",
                    "icon": c.get("icon", ""),
                }
                break

        if not category:
            print_error(f"Category not found: {category_id}")
            raise typer.Exit(1)

        if table:
            rows = [{"field": k, "value": str(v)} for k, v in category.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(category)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))
