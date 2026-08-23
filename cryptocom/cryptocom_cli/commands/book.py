"""Order book commands for Crypto.com Exchange."""
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

app = typer.Typer(help="Inspect order books", no_args_is_help=True)


@app.command("list")
@command
def book_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of instruments to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List instruments available for order book lookups."""
    instruments = get_client().list_instruments(limit=limit, filters=filter)
    emit(
        instruments,
        table=table,
        columns=["symbol", "inst_type", "display_name", "tradable"],
        properties=properties,
    )


@app.command("get")
@command
def book_get(
    instrument_name: str = typer.Argument(..., help="Instrument name, for example BTCUSD-PERP"),
    depth: int = typer.Option(10, "--depth", "-d", help="Order book depth"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get an order book snapshot."""
    snapshot = get_client().get_book(instrument_name=instrument_name, depth=depth)
    emit(
        snapshot,
        table=table,
        columns=["instrument_name", "depth", "t"],
        properties=properties,
    )
