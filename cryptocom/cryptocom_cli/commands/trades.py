"""Trade commands for Crypto.com Exchange."""
COMMAND_CREDENTIALS = {
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ]
}

from typing import List, Optional

import typer

from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import handle_error

from ..client import get_client
from ._display import emit

app = typer.Typer(help="Inspect public trades", no_args_is_help=True)


@app.command("list")
def trades_list(
    instrument_name: str = typer.Argument(..., help="Instrument name, for example BTCUSD-PERP"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(25, "--limit", "-l", help="Maximum number of trades to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    start_ts: Optional[str] = typer.Option(None, "--start-ts", help="Inclusive start timestamp"),
    end_ts: Optional[str] = typer.Option(None, "--end-ts", help="Exclusive end timestamp"),
):
    """List recent trades for an instrument."""
    try:
        trades = get_client().list_trades(
            instrument_name=instrument_name,
            limit=limit,
            start_ts=start_ts,
            end_ts=end_ts,
            filters=filter,
        )
        emit(
            trades,
            table=table,
            columns=["d", "i", "s", "p", "q", "t"],
            properties=properties,
        )
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def trades_get(
    trade_id: str = typer.Argument(..., help="Trade ID from trades list"),
    instrument_name: str = typer.Argument(..., help="Instrument name, for example BTCUSD-PERP"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one recent trade by ID."""
    try:
        trade = get_client().get_trade(instrument_name=instrument_name, trade_id=trade_id)
        emit(
            trade,
            table=table,
            columns=["d", "i", "s", "p", "q", "t"],
            properties=properties,
        )
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
