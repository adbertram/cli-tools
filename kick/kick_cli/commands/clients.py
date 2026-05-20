"""Clients commands for Kick CLI."""
import typer
from typing import Optional, List

from cli_tools_shared.filters import apply_filters
from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error

app = typer.Typer(help="Manage Kick clients")


@app.command("list")
def clients_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of clients to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of properties to display"),
    sort: str = typer.Option("name_asc", "--sort", help="Sort order (name_asc, name_desc)"),
):
    """
    List clients.

    Filter by name using API-level search, or use client-side filtering for other fields.

    Examples:
        kick clients list
        kick clients list --table
        kick clients list --filter "name:Acme"
        kick clients list --filter "name:like:%test%"
        kick clients list --filter "city:Chicago"
        kick clients list --limit 100
    """
    try:
        client = get_client()
        clients = client.list_clients(
            limit=limit,
            sort=sort,
            filters=filter,
        )

        # Flatten nested counterparty structure for filtering/display
        flattened = []
        for item in clients:
            c = item.get("counterparty", item)
            flattened.append(c)

        # Apply all filters client-side for exact matching
        # (API search is fuzzy, client-side ensures exact filter semantics)
        if filter:
            flattened = apply_filters(flattened, filter)

        if table:
            table_data = []
            for c in flattened:
                table_data.append({
                    "id": c.get("id", ""),
                    "name": c.get("name", ""),
                    "email": c.get("email") or "",
                    "website": c.get("website") or "",
                    "city": c.get("city") or "",
                })

            print_table(
                table_data,
                ["id", "name", "email", "website", "city"],
                ["ID", "Name", "Email", "Website", "City"],
            )
            from cli_tools_shared.output import print_info
            print_info(f"Found {len(flattened)} clients")
        else:
            print_json(flattened)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def clients_get(
    client_id: str = typer.Argument(..., help="The client UUID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for a specific client.

    Examples:
        kick clients get 019b7021-bfa4-7a86-b46f-304afb384221
        kick clients get 019b7021-bfa4-7a86-b46f-304afb384221 --table
    """
    try:
        client = get_client()
        c = client.get_client(client_id)

        if table:
            summary = [{
                "id": c.get("id", ""),
                "name": c.get("name", ""),
                "email": c.get("email") or "",
                "phone": c.get("phoneNumber") or "",
                "website": c.get("website") or "",
                "city": c.get("city") or "",
                "state": c.get("state") or "",
                "country": c.get("country") or "",
            }]

            print_table(
                summary,
                ["id", "name", "email", "phone", "website", "city", "state", "country"],
                ["ID", "Name", "Email", "Phone", "Website", "City", "State", "Country"],
            )
        else:
            print_json(c)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def clients_create(
    name: str = typer.Argument(..., help="Name of the client"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as table"),
):
    """
    Create a new client.

    Examples:
        kick clients create "Acme Corporation"
        kick clients create "New Client" --table
    """
    try:
        client = get_client()
        c = client.create_client(name=name)

        if table:
            summary = [{
                "id": c.get("id", ""),
                "name": c.get("name", ""),
                "created": c.get("createdAt", "")[:10] if c.get("createdAt") else "",
            }]

            print_table(
                summary,
                ["id", "name", "created"],
                ["ID", "Name", "Created"],
            )
            from cli_tools_shared.output import print_info
            print_info(f"Client '{name}' created successfully")
        else:
            print_json(c)

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "create": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ]
}
