"""Main entry point for Awin CLI."""
from . import __version__
from .config import get_config
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

app = create_app(name="awin", help="Awin Publisher API CLI", version=__version__)

from .commands import programmes, publishers

register_commands(app, get_config, publishers, name="publishers", help="Manage Awin publisher accounts", cli_name="awin")
register_commands(app, get_config, programmes, name="programmes", help="Manage Awin advertiser programmes", cli_name="awin")

app.add_typer(create_auth_app(get_config, tool_name="awin"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
