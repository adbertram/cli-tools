"""Main entry point for RevoUninstaller CLI."""
from . import __version__
from .config import get_config
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

app = create_app(name="revo-uninstaller", help="CLI interface for RevoUninstaller (browser automation)", version=__version__)

# Register command modules
from .commands import search
register_commands(app, get_config, search, name="search", help="Search revo-uninstaller")
app.add_typer(create_auth_app(get_config, tool_name="revo-uninstaller"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
