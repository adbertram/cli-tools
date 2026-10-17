"""Read-only account-owned API token discovery."""
COMMAND_CREDENTIALS = {"list": ["api_key"], "get": ["api_key"], "permissions": ["api_key"]}

from typing import Optional

import typer

from ..client import DEFAULT_LIST_LIMIT, get_client
from ..presentation import print_records as _output
from cli_tools_shared.output import command


app = typer.Typer(help="Read account token metadata; read success does not prove creation permission", no_args_is_help=True)
permissions_app = typer.Typer(help="Available permission catalog, not caller grants", no_args_is_help=True)


@app.command("list")
@command
def list_tokens(
    account: str = typer.Argument(..., help="Account name or ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(DEFAULT_LIST_LIMIT, "--limit", "-l", min=0, help="Maximum matching tokens; 0 returns all"),
    filter_str: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Client-side filter: field:op:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated output fields"),
):
    """List token metadata across pages; filters precede limit.

    Examples:
        cloudflare account-tokens list ACCOUNT_ID --limit 0
    """
    client = get_client()
    _output(client.list_account_tokens(client.resolve_account_id(account), limit, filter_str), table, properties)


@app.command("get")
@command
def get_token(
    token_id: str = typer.Argument(..., help="Token ID from account-tokens list"),
    account: str = typer.Argument(..., help="Account name or ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated output fields"),
):
    """Get token metadata and policies without retrieving its bearer value.

    Examples:
        cloudflare account-tokens get TOKEN_ID ACCOUNT_ID
    """
    client = get_client()
    _output(client.get_account_token(client.resolve_account_id(account), token_id), table, properties)


@permissions_app.command("list")
@command
def list_permissions(
    account: str = typer.Argument(..., help="Account name or ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(DEFAULT_LIST_LIMIT, "--limit", "-l", min=0, help="Maximum matching groups; 0 returns all"),
    filter_str: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Client-side filter: field:op:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated output fields"),
):
    """List available permission groups; these are not caller grants.

    Examples:
        cloudflare account-tokens permissions list ACCOUNT_ID --filter 'name:contains:Queues' --limit 0
    """
    client = get_client()
    _output(client.list_account_token_permissions(client.resolve_account_id(account), limit, filter_str), table, properties)


@permissions_app.command("get")
@command
def get_permission(
    permission_id: str = typer.Argument(..., help="Permission ID from permissions list"),
    account: str = typer.Argument(..., help="Account name or ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated output fields"),
):
    """Select one permission by ID from the permission catalog.

    Examples:
        cloudflare account-tokens permissions get PERMISSION_ID ACCOUNT_ID
    """
    client = get_client()
    _output(client.get_account_token_permission(client.resolve_account_id(account), permission_id), table, properties)


app.add_typer(permissions_app, name="permissions")
