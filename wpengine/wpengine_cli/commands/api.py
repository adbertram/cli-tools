"""WP Engine API inspection commands."""

from __future__ import annotations

from typing import Optional

import typer
from cli_tools_shared.output import command

from ..client import WpengineClient
from ._render import render_record

app = typer.Typer(help="Inspect the WP Engine API", no_args_is_help=True)


@app.command("status")
@command
def api_status(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
) -> None:
    """Return the public WP Engine API status."""
    status = WpengineClient(require_auth=False).get_api_status()
    render_record(status, table=table, properties=properties)


COMMAND_CREDENTIALS = {
    "status": ["no_auth"],
}
