"""Main entry point for Slack CLI."""
import os
from typing import Optional

import typer

from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from .client import ClientError, set_global_profile
from .config import get_config

app = create_app(
    name="slack",
    help="CLI interface for Slack API",
    version=__version__,
)

@app.callback(invoke_without_command=True)
def _main_callback(
    ctx: typer.Context,
    version_flag: Optional[bool] = typer.Option(
        None, "--version", "-v", help="Show version and exit", is_eager=True,
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Bypass response cache",
    ),
    profile: Optional[str] = typer.Option(
        None, "--profile", help="Use a specific authentication profile",
    ),
):
    if no_cache:
        os.environ["CACHE_ENABLED"] = "false"
    if version_flag:
        typer.echo(f"slack-cli version {__version__}")
        raise typer.Exit()
    if profile:
        set_global_profile(profile)
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()

# Register command modules
from .commands import auth, channels, dm, messages, users, files
from .commands import canvas, notifications, reminders
app.add_typer(auth.app, name="auth", help="Manage Slack API authentication")
app.add_typer(create_cache_app(get_config), name="cache", help="Manage CLI cache")
register_commands(app, get_config, canvas, name="canvas", help="Manage Slack canvases")
register_commands(app, get_config, channels, name="channels", help="Manage Slack channels")
register_commands(app, get_config, dm, name="dm", help="Manage direct messages")
register_commands(app, get_config, files, name="files", help="Manage Slack files")
register_commands(app, get_config, messages, name="messages", help="Manage Slack messages")
register_commands(app, get_config, notifications, name="notifications", help="View all notifications")
register_commands(app, get_config, users, name="users", help="Manage Slack users")
register_commands(app, get_config, reminders, name="reminders", help="Manage Slack saved items (reminders/Later)")
def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
