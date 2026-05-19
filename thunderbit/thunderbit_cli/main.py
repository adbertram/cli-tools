"""Main entry point for the Thunderbit CLI."""
from . import __version__
from .config import get_config
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

app = create_app(name="thunderbit", help="CLI interface for Thunderbit API", version=__version__)

# Register command modules
from .commands import distill, extract
register_commands(app, get_config, distill, name="distill", help="Distill web pages into Markdown")
register_commands(app, get_config, extract, name="extract", help="Extract structured JSON from web pages")

# Register shared apps
app.add_typer(create_auth_app(get_config, tool_name="thunderbit"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
