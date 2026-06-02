"""Order commands for DoorDash CLI."""
COMMAND_CREDENTIALS = {
    "get": ["browser_session"],
    "list": ["browser_session"],
    "reorder": ["browser_session"],
}

from pathlib import Path
from typing import List, Optional

import typer

from cli_tools_shared.filters import apply_filters, validate_filters
from cli_tools_shared.output import command, print_info

from . import emit_rows
from ..client import get_client

app = typer.Typer(help="Manage DoorDash orders", no_args_is_help=True)

COLUMNS = {
    "id": "ID",
    "orderUuid": "UUID",
    "createdAt": "Created",
    "fulfillmentType": "Type",
    "store.name": "Store",
    "grandTotal.displayString": "Total",
}
REORDER_COLUMNS = {
    "order_id": "Order ID",
    "order_uuid": "Order UUID",
    "cart_uuid": "Cart UUID",
    "cart_url": "Cart URL",
    "submitted": "Submitted",
}


@app.command("list")
@command
def orders_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of orders"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter: field:op:value (e.g., fulfillmentType:eq:DELIVERY)"
    ),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated properties"),
):
    """List recent orders."""
    if filter:
        validate_filters(filter)
    rows = get_client().list_orders(limit=limit)
    if filter:
        rows = apply_filters([r.model_dump(mode="json") for r in rows], filter)
    emit_rows(rows, table=table, properties=properties, columns=COLUMNS)


@app.command("get")
@command
def orders_get(
    order_id: str = typer.Argument(..., help="Order ID or UUID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated properties"),
):
    """Get details for a specific order."""
    emit_rows([get_client().get_order(order_id)], table=table, properties=properties, columns=COLUMNS)


@app.command("reorder")
@command
def orders_reorder(
    order_id: str = typer.Argument(..., help="Order ID or UUID to reorder"),
    confirm: bool = typer.Option(False, "--confirm", help="Actually place the order (charges saved payment)"),
    debug_dir: Optional[str] = typer.Option(None, "--debug-dir", help="Directory for failure artifacts (confirm mode)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as a table"),
):
    """Reorder a previous DoorDash order. Default is dry-run (no charge)."""
    result = get_client().reorder(
        order_id,
        confirm=confirm,
        log=print_info,
        debug_dir=Path(debug_dir).expanduser() if debug_dir else None,
    )
    emit_rows([result.to_dict()], table=table, properties=None, columns=REORDER_COLUMNS)
