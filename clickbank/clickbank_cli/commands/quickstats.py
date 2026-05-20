"""Quickstats commands for ClickBank CLI."""
COMMAND_CREDENTIALS = {
    "accounts": ["api_key"],
    "get": ["api_key"],
    "count": ["api_key"],
    "list": ["api_key"],
}

import typer
from typing import List, Optional

from cli_tools_shared.output import handle_error

from ..client import get_client
from . import emit_rows


app = typer.Typer(help="Manage ClickBank quickstats", no_args_is_help=True)

DEFAULT_COLUMNS = [
    "nickName",
    "quickStats.0.quickStatDate",
    "quickStats.0.sale",
    "quickStats.0.refund",
    "quickStats.0.chargeback",
]
DEFAULT_HEADERS = [
    "Account",
    "Quickstat Date",
    "Sale",
    "Refund",
    "Chargeback",
]

@app.command("accounts")
def quickstats_accounts(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List account nicknames visible to the API key."""
    try:
        rows = get_client().list_quickstats_accounts()
        emit_rows(
            rows,
            table=table,
            properties=properties,
            default_columns=DEFAULT_COLUMNS,
            default_headers=DEFAULT_HEADERS,
        )
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def quickstats_get(
    account: str = typer.Argument(..., help="ClickBank account nickname"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get quickstats rows for a single ClickBank account nickname."""
    try:
        rows = get_client().get_quickstats_account(account)
        emit_rows(
            rows,
            table=table,
            properties=properties,
            default_columns=DEFAULT_COLUMNS,
            default_headers=DEFAULT_HEADERS,
        )
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("count")
def quickstats_count(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value",
    ),
):
    """Return summed quickstats for the requested period."""
    try:
        rows = get_client().count_quickstats(filters=filter)
        emit_rows(
            rows,
            table=table,
            properties=None,
            default_columns=DEFAULT_COLUMNS,
            default_headers=DEFAULT_HEADERS,
        )
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("list")
def quickstats_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, help="Maximum account rows to return"),
    page: int = typer.Option(1, "--page", min=1, help="Starting ClickBank page number"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value",
    ),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List quickstats grouped by account nickname."""
    try:
        rows = get_client().list_quickstats(limit=limit, page=page, filters=filter)
        emit_rows(
            rows,
            table=table,
            properties=properties,
            default_columns=DEFAULT_COLUMNS,
            default_headers=DEFAULT_HEADERS,
        )
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
