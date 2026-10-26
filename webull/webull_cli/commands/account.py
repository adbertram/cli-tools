"""Account and position commands."""
from __future__ import annotations
from typing import List, Optional
import typer
from cli_tools_shared.output import command, print_json
from ..client import WebullClient, WebullError
from ..presentation import guard, render

app = typer.Typer(help="Inspect accounts", no_args_is_help=True)
COMMAND_CREDENTIALS = {name: ["custom"] for name in ("list", "get", "balance", "positions")}

@app.command("list")
@command
@guard
def list_accounts(
    limit: Optional[int] = typer.Option(None, "--limit", "-l", min=1, help="Maximum accounts (local limit; Webull has no pagination)"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Local field:op:value filter"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated output fields"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """List accounts, preserving every API field by default."""
    render(WebullClient().account_list(), table=table, filters=filter, properties=properties, limit=limit)


@app.command("get")
@app.command("balance")
@command
@guard
def account_balance(account: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get an account's full balance response."""
    render(WebullClient().balance(account), table=table)


@app.command("positions")
@command
@guard
def account_positions(
    account: str,
    limit: Optional[int] = typer.Option(None, "--limit", "-l", min=1, help="Maximum positions (local limit; Webull has no pagination)"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Local field:op:value filter"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated output fields"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """List account positions."""
    render(WebullClient().positions(account), table=table, filters=filter, properties=properties, limit=limit)

