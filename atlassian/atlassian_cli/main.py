"""Main entry point for Atlassian CLI."""

from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

from .commands import app as search_app
from . import commands
from .config import get_config

app = create_app(name="atlassian", help="CLI interface for Atlassian (browser automation)", version=__version__)

register_commands(app, get_config, commands, name="search", help="Search Atlassian")
app.add_typer(create_auth_app(get_config, tool_name="atlassian"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
