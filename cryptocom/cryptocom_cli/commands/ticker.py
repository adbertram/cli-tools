"""Ticker commands for Crypto.com Exchange."""
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
from cli_tools_shared.output import command

from ..client import get_client
from ._display import emit

app = typer.Typer(help="Inspect instrument tickers", no_args_is_help=True)


@app.command("list")
@command
def ticker_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of tickers to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List tickers."""
    tickers = get_client().list_tickers(limit=limit, filters=filter)
    emit(
        tickers,
        table=table,
        columns=["i", "a", "b", "k", "h", "l", "v", "t"],
        properties=properties,
    )


@app.command("get")
@command
def ticker_get(
    instrument_name: str = typer.Argument(..., help="Instrument name, for example BTCUSD-PERP"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get ticker data for an instrument."""
    ticker = get_client().get_ticker(instrument_name=instrument_name)
    emit(
        ticker,
        table=table,
        columns=["i", "a", "b", "k", "h", "l", "v", "t"],
        properties=properties,
    )
