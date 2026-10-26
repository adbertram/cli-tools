"""Webull CLI entry point and resolved transport configuration."""
from __future__ import annotations
import sys
import getpass
from typing import Optional
import typer
from cli_tools_shared import create_app, run_app, register_commands
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.config import set_runtime_profile_resolution
from cli_tools_shared.output import command, print_json
from . import __version__
from .client import Options, WebullError, configure
from .config import get_config
from .presentation import guard
from .commands import account, order, futures

app = create_app(name="webull", help="Webull OpenAPI accounts, orders and futures data", version=__version__, cache_support=False)
auth_app = create_auth_app(get_config, tool_name="webull")

@app.callback(invoke_without_command=True)
def callback(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", is_eager=True, help="Show version and exit"),
    environment: str = typer.Option("sandbox", "--environment", help="sandbox or live"),
    confirm_live: bool = typer.Option(False, "--confirm-live", help="Explicitly authorize production Webull access"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Saved authentication profile"),
    region: str = typer.Option("us", "--region", help="Webull region"),
    api_host: Optional[str] = typer.Option(None, "--api-host", help="Explicit API hostname"),
    quotes_api_host: Optional[str] = typer.Option(None, "--quotes-api-host", help="Explicit quotes API hostname"),
    events_api_host: Optional[str] = typer.Option(None, "--events-api-host", help="Explicit events API hostname"),
    connect_timeout: float = typer.Option(3.0, "--connect-timeout", min=0.001, help="HTTP connect timeout in seconds"),
    read_timeout: float = typer.Option(6.0, "--read-timeout", min=0.001, help="HTTP read timeout in seconds"),
    no_cache: bool = typer.Option(False, "--no-cache", hidden=True),
):
    if version:
        typer.echo(f"webull-cli version {__version__}")
        raise typer.Exit()
    configure(Options(environment, confirm_live, profile, region, api_host, quotes_api_host, events_api_host, connect_timeout, read_timeout))
    set_runtime_profile_resolution(profile_name=profile, profile_auth_type=None)
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@auth_app.command("token")
@command
@guard
def save_token(profile: Optional[str] = typer.Option(None, "--profile", help="Authentication profile")):
    """Save an access token from a hidden terminal prompt or piped stdin."""
    token = (getpass.getpass("Authorized Webull access token: ") if sys.stdin.isatty() else sys.stdin.read()).strip()
    if not token:
        raise WebullError("validation", "Provide the authorized access token on stdin.")
    get_config(profile).save_credentials(ACCESS_TOKEN=token)
    print_json({"saved": True})


register_commands(app, get_config, account, name="account", help="Inspect Webull accounts", cli_name="webull")
register_commands(app, get_config, order, name="order", help="Inspect and manage broker orders", cli_name="webull")
register_commands(app, get_config, futures, name="futures", help="Read futures market data", cli_name="webull")
app.add_typer(auth_app, name="auth")


def main():
    run_app(app)


if __name__ == "__main__":
    main()
