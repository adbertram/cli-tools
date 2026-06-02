"""Order commands for ClickBank CLI."""
COMMAND_CREDENTIALS = {
    "get": ["api_key"],
    "list": ["api_key"],
    "count": ["api_key"],
    "upsells": ["api_key"],
}

import typer
from typing import List, Optional

from cli_tools_shared.filters import FilterValidationError
from cli_tools_shared.output import handle_error, print_json, print_table

from ..client import get_client
from . import emit_rows


app = typer.Typer(help="Manage ClickBank orders", no_args_is_help=True)

DEFAULT_COLUMNS = [
    "receipt",
    "transactionTime",
    "transactionType",
    "vendor",
    "affiliate",
    "totalOrderAmount",
    "currency",
]
DEFAULT_HEADERS = [
    "Receipt",
    "Transaction Time",
    "Type",
    "Vendor",
    "Affiliate",
    "Amount",
    "Currency",
]

@app.command("get")
def orders_get(
    receipt: str = typer.Argument(..., help="Receipt number"),
    sku: Optional[str] = typer.Option(None, "--sku", help="SKU for multi-item cart receipts"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get order details for a receipt."""
    try:
        rows = get_client().get_order(receipt, sku=sku)
        emit_rows(
            rows,
            table=table,
            properties=properties,
            default_columns=DEFAULT_COLUMNS,
            default_headers=DEFAULT_HEADERS,
        )
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("list")
def orders_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, help="Maximum orders to return"),
    page: int = typer.Option(1, "--page", min=1, help="Starting ClickBank page number"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value",
    ),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List orders visible to the authenticated ClickBank API key."""
    try:
        rows = get_client().list_orders(limit=limit, filters=filter, page=page)
        emit_rows(
            rows,
            table=table,
            properties=properties,
            default_columns=DEFAULT_COLUMNS,
            default_headers=DEFAULT_HEADERS,
        )
    except (FilterValidationError, Exception) as exc:
        raise typer.Exit(handle_error(exc))


@app.command("count")
def orders_count(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value",
    ),
):
    """Count orders matching documented ClickBank filters."""
    try:
        result = get_client().count_orders(filters=filter)
        if table:
            print_table([result], ["count"], ["Count"])
            return
        print_json(result)
    except (FilterValidationError, Exception) as exc:
        raise typer.Exit(handle_error(exc))


@app.command("upsells")
def orders_upsells(
    receipt: str = typer.Argument(..., help="Initial transaction receipt"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List upsell transactions for a parent receipt."""
    try:
        rows = get_client().get_order_upsells(receipt)
        emit_rows(
            rows,
            table=table,
            properties=properties,
            default_columns=DEFAULT_COLUMNS,
            default_headers=DEFAULT_HEADERS,
        )
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
