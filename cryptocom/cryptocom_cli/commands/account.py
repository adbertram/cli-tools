"""Private account commands for Crypto.com Exchange."""
COMMAND_CREDENTIALS = {
    "balance": [
        "custom"
    ],
    "open-orders": [
        "custom"
    ],
    "positions": [
        "custom"
    ]
}

from typing import List, Optional

import typer

from cli_tools_shared.output import command

from ..client import get_client
from ._display import emit

app = typer.Typer(help="Inspect authenticated account data", no_args_is_help=True)


@app.command("balance")
@command
def account_balance(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of balances to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get account balances."""
    balances = get_client().get_balances(limit=limit, filters=filter)
    emit(
        balances,
        table=table,
        columns=["instrument_name", "total_available_balance", "total_cash_balance", "total_collateral_value"],
        properties=properties,
    )


@app.command("positions")
@command
def account_positions(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of positions to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., instrument_name:eq:BTC, market_value:gt:10)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get positive non-USD spot positions."""
    positions = get_client().get_positions(limit=limit, filters=filter)
    emit(
        positions,
        table=table,
        columns=["instrument_name", "quantity", "market_value"],
        properties=properties,
    )


@app.command("open-orders")
@command
def account_open_orders(
    instrument_name: Optional[str] = typer.Option(None, "--instrument-name", "-i", help="Instrument name"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of open orders to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List open orders."""
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
