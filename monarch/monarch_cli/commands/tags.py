"""Tags commands for Monarch CLI."""
import typer
from typing import Optional, List

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_error, handle_error
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError

app = typer.Typer(help="Manage transaction tags")

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
def tags_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum tags to return"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., name:like:%work%)",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """
    List all transaction tags.

    Filter Examples:
        monarch tags list --filter "name:like:%work%"
        monarch tags list --filter "color:blue"
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
        data = client.get_tags()

        tags = data.get("householdTransactionTags", [])[:limit]

        # Normalize to dicts with id field
        rows = []
        for t in tags:
            rows.append({
                "id": t.get("id", ""),
                "name": t.get("name", ""),
                "color": t.get("color", ""),
            })

        # Apply client-side filters
        if filter:
            rows = apply_filters(rows, filter)

        # Apply properties filter
        if properties:
            rows = _apply_properties_filter(rows, properties)

        if table:
            cols = list(rows[0].keys()) if rows else ["id", "name", "color"]
            print_table(rows, cols, [c.title() for c in cols])
        else:
            print_json(rows)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def tags_get(
    tag_id: str = typer.Argument(..., help="Tag ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get details for a specific tag."""
    try:
        client = get_client()
        data = client.get_tags()
        tags = data.get("householdTransactionTags", [])

        tag = None
        for t in tags:
            if str(t.get("id", "")) == str(tag_id):
                tag = {
                    "id": t.get("id", ""),
                    "name": t.get("name", ""),
                    "color": t.get("color", ""),
                }
                break

        if not tag:
            print_error(f"Tag not found: {tag_id}")
            raise typer.Exit(1)

        if table:
            rows = [{"field": k, "value": str(v)} for k, v in tag.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(tag)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))
