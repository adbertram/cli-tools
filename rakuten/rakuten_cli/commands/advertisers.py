"""Advertiser commands for Rakuten CLI."""
from typing import List, Optional

import typer

from cli_tools_shared.output import handle_error

from ..client import get_client
from ._common import output_item, output_list


COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
}

app = typer.Typer(help="Manage Rakuten Advertising advertiser programs", no_args_is_help=True)


@app.command("list")
def advertisers_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (eq only)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    status: str = typer.Option("approved", "--status", "-s", help="Application status: approved, declined, pending, all"),
):
    """List advertisers visible to the publisher."""
    try:
        items = get_client().list_advertisers(status=status, limit=limit, filters=filter)
        output_list(
            items,
            table,
            properties,
            ["mid", "name", "applicationStatus"],
            ["Merchant ID", "Name", "App Status"],
        )
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def advertisers_get(
    mid: str = typer.Argument(..., help="Rakuten merchant id (mid)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get one advertiser by merchant id."""
    try:
        item = get_client().get_advertiser(mid)
        output_item(item, table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
