"""`legoscout display` -- the local deals web page and the rows it renders."""
from __future__ import annotations

import json
from typing import Optional

import typer
from cli_tools_shared.output import command

from .. import delegate
from ..display import rows as rows_module, server as server_module

COMMAND_CREDENTIALS = ["no_auth"]

app = typer.Typer(help="The local deals web page", no_args_is_help=True)


@app.command("serve")
@command
def serve(
    host: str = typer.Option(
        "127.0.0.1", "--host", help="Interface to bind. adam-server's pm2 deploy uses its "
        "Tailscale IP; local debugging keeps the loopback default."),
    port: int = typer.Option(server_module.DEFAULT_PORT, "--port", help="Port to listen on"),
    no_open: bool = typer.Option(False, "--no-open", help="Do not open a browser"),
    db: Optional[str] = typer.Option(
        None, "--db", help="A different ledger, for probes. Applies to every route."),
):
    """Serve the deals page. Runs until stopped -- ctrl-c locally, pm2 on adam-server."""
    argv = ["--host", host, "--port", str(port)]
    delegate.flag(argv, "--no-open", no_open)
    delegate.option(argv, "--db", db)
    delegate.run(server_module, argv)


@app.command("rows")
@command
def rows(
    active_only: bool = typer.Option(
        False, "--active-only", help="Drop rejected rows as well as unavailable and blocked"),
    db: Optional[str] = typer.Option(None, "--db", help="A different ledger, for probes"),
):
    """Print the deals-table rows as JSON. Node is not involved."""
    print(json.dumps({"rows": rows_module.build_rows(active_only, db)}))
