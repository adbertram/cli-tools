"""WP Engine site commands."""

from __future__ import annotations

from typing import Optional

import typer
from cli_tools_shared.output import command

from ..client import get_client
from ._render import render_list, render_record

app = typer.Typer(help="List and inspect WP Engine sites", no_args_is_help=True)

DEFAULT_COLUMNS = ["id", "name", "account_id"]


@app.command("list")
@command
def sites_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of sites to return"),
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (account_id:eq:... is sent to the API)",
    ),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
) -> None:
    """List WP Engine sites."""
    sites = get_client().list_sites(limit=limit, filters=filter)
    render_list(sites, table=table, properties=properties, default_columns=DEFAULT_COLUMNS)


@app.command("get")
@command
def sites_get(
    site_id: str = typer.Argument(..., help="WP Engine site ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
) -> None:
    """Get one WP Engine site by ID."""
    site = get_client().get_site(site_id)
    render_record(site, table=table, properties=properties)


COMMAND_CREDENTIALS = {
    "get": ["username_password"],
    "list": ["username_password"],
}
