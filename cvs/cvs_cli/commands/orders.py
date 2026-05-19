"""Order commands for CVS CLI."""
COMMAND_CREDENTIALS = {
    "get": [
        "browser_session"
    ],
    "list": [
        "browser_session"
    ]
}

import typer
from typing import List, Optional

from pydantic import BaseModel

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error
from cli_tools_shared.filters import apply_filters, apply_limit, apply_properties_filter


app = typer.Typer(help="Manage orders", no_args_is_help=True)


def model_to_dict(item):
    """Convert model or dict to dict for field extraction."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


DEFAULT_TABLE_COLS = [
    "orderId",
    "orderDate",
    "orderStatus",
    "drugName",
    "patientFirstName",
    "fulfillmentType",
    "cost",
]
DEFAULT_TABLE_HEADERS = [
    "Order ID",
    "Date",
    "Status",
    "Drug",
    "Patient",
    "Fulfillment",
    "Cost",
]


@app.command("list")
def orders_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """List order history."""
    try:
        client = get_client()
        items = client.list_orders()
        items = [i.model_dump() for i in items]
        if filter:
            items = apply_filters(items, filter)
        items = apply_limit(items, limit)
        if properties:
            items = apply_properties_filter(items, properties)
        if table:
            if properties:
                cols = [c.strip() for c in properties.split(",")]
                headers = cols
            else:
                cols = DEFAULT_TABLE_COLS
                headers = DEFAULT_TABLE_HEADERS
            print_table(items, cols, headers)
        else:
            print_json(items)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def orders_get(
    order_id: str = typer.Argument(..., help="Order ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get a specific order."""
    try:
        client = get_client()
        item = client.get_order(order_id)
        data = item.model_dump()
        if table:
            print_table([data], list(data.keys()), list(data.keys()))
        else:
            print_json(data)
    except Exception as e:
        raise typer.Exit(handle_error(e))
