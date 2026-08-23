"""WP Engine environment commands."""

from __future__ import annotations

from typing import Optional

import typer
from cli_tools_shared.output import command

from ..client import get_client
from ._render import render_list, render_record

app = typer.Typer(help="List and inspect WP Engine environments", no_args_is_help=True)

DEFAULT_COLUMNS = ["id", "name", "environment", "site_id", "account_id"]


@app.command("list")
@command
def environments_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of environments to return"),
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (account_id:eq:... is sent to the API)",
    ),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
) -> None:
    """List WP Engine environments, documented by the API as installs."""
    environments = get_client().list_environments(limit=limit, filters=filter)
    render_list(environments, table=table, properties=properties, default_columns=DEFAULT_COLUMNS)


@app.command("get")
@command
def environments_get(
    environment_id: str = typer.Argument(..., help="WP Engine environment/install ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
) -> None:
    """Get one WP Engine environment by install ID."""
    environment = get_client().get_environment(environment_id)
    render_record(environment, table=table, properties=properties)


COMMAND_CREDENTIALS = {
    "get": ["username_password"],
    "list": ["username_password"],
}
