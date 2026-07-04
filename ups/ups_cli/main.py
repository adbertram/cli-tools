"""Main entry point for UPS CLI."""

from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

from . import __version__
from .client import ClientError, ups_oauth_login
from .config import get_config

app = create_app(name="ups", help="CLI interface for UPS Pickup API", version=__version__)

from . import commands

app.add_typer(
    create_auth_app(get_config, tool_name="ups", login_handler=ups_oauth_login),
    name="auth",
    help="Manage UPS API authentication",
)
app.add_typer(create_cache_app(get_config), name="cache", help="Manage response cache")
register_commands(app, get_config, commands, name="pickup", help="Schedule and inspect UPS pickups")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
