"""WP Engine account commands."""

from __future__ import annotations

from typing import Optional

import typer
from cli_tools_shared.output import command

from ..client import get_client
from ._render import render_list, render_record

app = typer.Typer(help="List and inspect WP Engine accounts", no_args_is_help=True)

DEFAULT_COLUMNS = ["id", "name"]


@app.command("list")
@command
def accounts_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of accounts to return"),
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (for example, name:contains:ATA)",
    ),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
) -> None:
    """List WP Engine accounts available to the API user."""
    accounts = get_client().list_accounts(limit=limit, filters=filter)
    render_list(accounts, table=table, properties=properties, default_columns=DEFAULT_COLUMNS)


@app.command("get")
@command
def accounts_get(
    account_id: str = typer.Argument(..., help="WP Engine account ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
) -> None:
    """Get one WP Engine account by ID."""
    account = get_client().get_account(account_id)
    render_record(account, table=table, properties=properties)


COMMAND_CREDENTIALS = {
    "get": ["username_password"],
    "list": ["username_password"],
}
