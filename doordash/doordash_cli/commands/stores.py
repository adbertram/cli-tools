"""Store commands for DoorDash CLI."""
COMMAND_CREDENTIALS = {
    "get": ["browser_session"],
    "list": ["browser_session"],
}

from typing import List, Optional

import typer

from cli_tools_shared.filters import apply_filters, validate_filters
from cli_tools_shared.output import command

from . import emit_rows
from ..client import ClientError, get_client

app = typer.Typer(help="Browse available stores/restaurants", no_args_is_help=True)

COLUMNS = {
    "id": "ID",
    "name": "Name",
    "rating": "Rating",
    "deliveryFeeCents": "Fee (cents)",
    "deliveryMinutes": "Minutes",
    "isOpen": "Open",
}


@app.command("list")
@command
def stores_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of stores"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter: field:op:value (e.g., isOpen:eq:true, rating:gte:4.5)"
    ),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated properties"),
):
    """List available stores/restaurants near your saved delivery address."""
    if filter:
        validate_filters(filter)
    rows = get_client().list_stores(limit=limit)
    if filter:
        rows = apply_filters([r.model_dump(mode="json") for r in rows], filter)
    emit_rows(rows, table=table, properties=properties, columns=COLUMNS)


@app.command("get")
@command
def stores_get(
    store_id: str = typer.Argument(..., help="Store ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated properties"),
):
    """Get a store from the current store feed by ID."""
    matches = [s for s in get_client().list_stores(limit=100) if s.id == store_id]
    if not matches:
        raise ClientError(f"Store not found: {store_id}")
    emit_rows(matches, table=table, properties=properties, columns=COLUMNS)
