"""Instance read-outs: health, version, statistics, public config, identity."""

COMMAND_CREDENTIALS = {
    "health": ["no_auth"],
    "config": ["no_auth"],
    "status": ["browser_session"],
    "statistics": ["browser_session"],
    "whoami": ["browser_session"],
}

import typer
from cli_tools_shared.output import command, print_json

from ..client import get_client

app = typer.Typer(help="Inspect the Garrul instance", no_args_is_help=True)


@app.command("health")
@command
def health():
    """Check that the instance is up. Needs no sign-in."""
    print_json(get_client().get_health())


@app.command("config")
@command
def public_config():
    """Show the public widget configuration the instance serves to embedding pages."""
    print_json(get_client().get_public_config())


@app.command("status")
@command
def status():
    """Show the running Garrul version and the releases the instance knows about."""
    print_json(get_client().get_status())


@app.command("statistics")
@command
def statistics():
    """Show dashboard totals: comments, pending, spam, users, and per-domain counts."""
    print_json(get_client().get_statistics())


@app.command("whoami")
@command
def whoami():
    """Show which Garrul user this CLI is signed in as."""
    print_json(get_client().get_me())
