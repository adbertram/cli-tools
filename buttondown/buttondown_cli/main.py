"""Main entry point for Buttondown CLI."""
from __future__ import annotations

from typing import Optional
import os

import typer

from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

from . import __version__
from .client import ClientError, set_global_profile
from .config import get_config


app = create_app(name="buttondown", help="CLI interface for Buttondown API", version=__version__)


@app.callback(invoke_without_command=True)
def callback(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(None, "--version", "-v", help="Show version and exit", is_eager=True),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass response cache"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Use a specific authentication profile"),
):
    """Handle global options."""
    if no_cache:
        os.environ["CACHE_ENABLED"] = "false"
    if version:
        typer.echo(f"buttondown-cli version {__version__}")
        raise typer.Exit()
    if profile is not None:
        set_global_profile(profile)
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


from .commands import automations, emails, feeds, subscribers, tags

app.add_typer(create_auth_app(get_config, tool_name="buttondown"), name="auth", help="Manage authentication")
app.add_typer(create_cache_app(get_config), name="cache", help="Manage response cache")
register_commands(app, get_config, automations, name="automations", help="Manage automations", cli_name="buttondown")
register_commands(app, get_config, emails, name="emails", help="Manage emails", cli_name="buttondown")
register_commands(app, get_config, feeds, name="feeds", help="Manage RSS-to-email external feeds", cli_name="buttondown")
register_commands(app, get_config, subscribers, name="subscribers", help="Manage subscribers", cli_name="buttondown")
register_commands(app, get_config, tags, name="tags", help="Manage tags", cli_name="buttondown")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
