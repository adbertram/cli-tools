"""Main entry point for Azlogs CLI."""
import typer
from typing import Optional
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.command_registry import register_commands
from .client import ClientError
from .config import get_config

app = create_app(
    name="azlogs",
    help="Download, parse, and analyze Azure Web App logs via Kudu API",
    version=__version__,
)

# Register command modules
from .commands import auth, packages, entries, report
from cli_tools_shared.cache_commands import create_cache_app
app.add_typer(auth.app, name="auth", help="Check Azure CLI authentication status")
app.add_typer(create_cache_app(get_config), name="cache", help="Manage CLI cache")
register_commands(app, get_config, packages, name="packages", help="Manage downloaded log packages")
register_commands(app, get_config, entries, name="entries", help="Query parsed log entries")
register_commands(app, get_config, report, name="report", help="Generate log analysis reports")
@app.callback(invoke_without_command=True)
def callback(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", help="Show version and exit", is_eager=True
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Bypass response cache"
    ),
    # Top-level options — required for commands that connect to Azure (e.g. packages download)
    app_name: Optional[str] = typer.Option(
        None, "--app", "-a", help="Azure Web App name",
    ),
    resource_group: Optional[str] = typer.Option(
        None, "--resource-group", "-g", help="Azure Resource Group",
    ),
):
    """Azlogs CLI — Download, parse, and analyze Azure Web App logs."""
    import os
    if no_cache:
        os.environ["CACHE_ENABLED"] = "false"
    if version:
        typer.echo(f"azlogs-cli version {__version__}")
        raise typer.Exit()

    # Store on config singleton so client can access them
    config = get_config()
    if app_name:
        config.app_name = app_name
    if resource_group:
        config.resource_group = resource_group

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
