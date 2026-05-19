"""Main entry point for Rakuten Advertising CLI."""
from . import __version__
from .config import get_config
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

app = create_app(name="rakuten", help="Rakuten Advertising Publisher API CLI", version=__version__)

from .commands import advertisers

register_commands(
    app,
    get_config,
    advertisers,
    name="advertisers",
    help="Manage advertiser programs",
    cli_name="rakuten",
)

app.add_typer(create_auth_app(get_config, tool_name="rakuten"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
