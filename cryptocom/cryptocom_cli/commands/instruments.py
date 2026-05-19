"""Instrument commands for Crypto.com Exchange."""
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

app = typer.Typer(help="Inspect Exchange instruments", no_args_is_help=True)


@app.command("list")
def instruments_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of instruments to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List instruments."""
    try:
        instruments = get_client().list_instruments(limit=limit, filters=filter)
        emit(
            instruments,
            table=table,
            columns=["symbol", "inst_type", "display_name", "base_ccy", "quote_ccy", "tradable"],
            properties=properties,
        )
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def instruments_get(
    symbol: str = typer.Argument(..., help="Instrument symbol, for example BTCUSD-PERP"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one instrument."""
    try:
        instrument = get_client().get_instrument(symbol=symbol)
        emit(
            instrument,
            table=table,
            columns=["symbol", "inst_type", "display_name", "base_ccy", "quote_ccy", "tradable"],
            properties=properties,
        )
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
