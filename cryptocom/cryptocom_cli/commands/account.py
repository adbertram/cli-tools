"""Private account commands for Crypto.com Exchange."""
COMMAND_CREDENTIALS = {
    "fee-rate": ["custom"],
    "instrument-fee-rate": ["custom"],
    "fills": ["custom"],
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


@app.command("fee-rate")
@command
def account_fee_rate(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get actual account fee rates in basis points (1 bps = 0.0001)."""
    emit(get_client().get_fee_rate(), table=table,
         columns=["effective_spot_maker_rate_bps", "effective_spot_taker_rate_bps"],
         properties=properties)


@app.command("instrument-fee-rate")
@command
def account_instrument_fee_rate(
    instrument_name: str = typer.Argument(..., help="Instrument name, for example SOL_USD"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get actual instrument fee rates in basis points (1 bps = 0.0001)."""
    emit(get_client().get_instrument_fee_rate(instrument_name), table=table,
         columns=["instrument_name", "effective_maker_rate_bps", "effective_taker_rate_bps"],
         properties=properties)


@app.command("fills")
@command
def account_fills(
    instrument_name: Optional[str] = typer.Option(None, "--instrument-name", "-i", help="Instrument name"),
    start_time: Optional[int] = typer.Option(None, "--start-time", help="Inclusive start timestamp in milliseconds or nanoseconds"),
    end_time: Optional[int] = typer.Option(None, "--end-time", help="Exclusive end timestamp in milliseconds or nanoseconds"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=100, help="Maximum rows in one venue page; no automatic pagination"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter returned page: field:op:value"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Read one private trade-fill page; negative fees mean a balance deduction."""
    rows = get_client().get_history_page(
        "private/get-trades", instrument_name=instrument_name,
        start_time=start_time, end_time=end_time, limit=limit, filters=filter,
    )
    emit(rows, table=table,
         columns=["trade_id", "order_id", "instrument_name", "traded_quantity", "traded_price", "fees", "fee_instrument_name"],
         properties=properties)
