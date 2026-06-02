"""Institutions commands for Monarch CLI."""
import typer
from typing import Optional, List

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_error, handle_error
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError

app = typer.Typer(help="Manage linked financial institutions")

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
def institutions_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum institutions to return"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., name:like:%Chase%, update_required:true)",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """
    List all linked financial institutions.

    Filter Examples:
        monarch institutions list --filter "name:like:%Chase%"
        monarch institutions list --filter "update_required:true"
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
        data = client.get_institutions()

        credentials = data.get("credentials", [])[:limit]

        # Normalize to dicts with id field
        rows = []
        for cred in credentials:
            inst = cred.get("institution", {})
            rows.append({
                "id": cred.get("id", ""),
                "name": inst.get("name", ""),
                "provider": cred.get("dataProvider", ""),
                "update_required": cred.get("updateRequired", False),
            })

        # Apply client-side filters
        if filter:
            rows = apply_filters(rows, filter)

        # Apply properties filter
        if properties:
            rows = _apply_properties_filter(rows, properties)

        if table:
            cols = list(rows[0].keys()) if rows else ["id", "name", "provider", "update_required"]
            print_table(rows, cols, [c.replace("_", " ").title() for c in cols])
        else:
            print_json(rows)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def institutions_get(
    institution_id: str = typer.Argument(..., help="Institution credential ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get details for a specific linked institution."""
    try:
        client = get_client()
        data = client.get_institutions()
        credentials = data.get("credentials", [])

        institution = None
        for cred in credentials:
            if str(cred.get("id", "")) == str(institution_id):
                inst = cred.get("institution", {})
                institution = {
                    "id": cred.get("id", ""),
                    "name": inst.get("name", ""),
                    "provider": cred.get("dataProvider", ""),
                    "update_required": cred.get("updateRequired", False),
                }
                break

        if not institution:
            print_error(f"Institution not found: {institution_id}")
            raise typer.Exit(1)

        if table:
            rows = [{"field": k, "value": str(v)} for k, v in institution.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(institution)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))
