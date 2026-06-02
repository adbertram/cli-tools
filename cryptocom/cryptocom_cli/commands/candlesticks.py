"""Candlestick commands for Crypto.com Exchange."""
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

app = typer.Typer(help="Inspect candlesticks", no_args_is_help=True)


@app.command("list")
def candlesticks_list(
    instrument_name: str = typer.Argument(..., help="Instrument name, for example BTCUSD-PERP"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(25, "--limit", "-l", help="Maximum number of candles to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    timeframe: str = typer.Option("1m", "--timeframe", help="Candlestick timeframe"),
    start_ts: Optional[str] = typer.Option(None, "--start-ts", help="Inclusive start timestamp"),
    end_ts: Optional[str] = typer.Option(None, "--end-ts", help="Exclusive end timestamp"),
):
    """List candlesticks for an instrument."""
    try:
        candles = get_client().list_candlesticks(
            instrument_name=instrument_name,
            timeframe=timeframe,
            limit=limit,
            start_ts=start_ts,
            end_ts=end_ts,
            filters=filter,
        )
        emit(
            candles,
            table=table,
            columns=["t", "o", "h", "l", "c", "v"],
            properties=properties,
        )
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def candlesticks_get(
    instrument_name: str = typer.Argument(..., help="Instrument name, for example BTCUSD-PERP"),
    timestamp: int = typer.Argument(..., help="Candlestick start timestamp in milliseconds"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    timeframe: str = typer.Option("1m", "--timeframe", help="Candlestick timeframe"),
):
    """Get one recent candlestick by timestamp."""
    try:
        candle = get_client().get_candlestick(
            instrument_name=instrument_name,
            timestamp=timestamp,
            timeframe=timeframe,
        )
        emit(
            candle,
            table=table,
            columns=["t", "o", "h", "l", "c", "v"],
            properties=properties,
        )
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
