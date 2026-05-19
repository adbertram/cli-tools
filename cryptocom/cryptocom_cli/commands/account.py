"""Private account commands for Crypto.com Exchange."""
COMMAND_CREDENTIALS = {
    "balance": [
        "custom"
    ],
    "open-orders": [
        "custom"
    ]
}

from typing import List, Optional

import typer

from cli_tools_shared.output import handle_error

from ..client import get_client
from ._display import emit

app = typer.Typer(help="Inspect authenticated account data", no_args_is_help=True)


@app.command("balance")
def account_balance(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of balances to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get account balances."""
    try:
        balances = get_client().get_balances(limit=limit, filters=filter)
        emit(
            balances,
            table=table,
            columns=["instrument_name", "total_available_balance", "total_cash_balance", "total_collateral_value"],
            properties=properties,
        )
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("open-orders")
def account_open_orders(
    instrument_name: Optional[str] = typer.Option(None, "--instrument-name", "-i", help="Instrument name"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of open orders to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List open orders."""
    try:
        orders = get_client().list_open_orders(
            instrument_name=instrument_name,
            limit=limit,
            filters=filter,
        )
        emit(
            orders,
            table=table,
            columns=["order_id", "instrument_name", "side", "order_type", "quantity", "limit_price", "status"],
            properties=properties,
        )
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
