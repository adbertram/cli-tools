"""Main entry point for Pluralsight CLI."""
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

from . import __version__
from .config import get_config
from .commands import program

app = create_app(
    name="pluralsight",
    help="CLI interface for the Pluralsight affiliate program",
    version=__version__,
)
register_commands(app, get_config, program, name="program", help="Show program metadata")
app.add_typer(create_auth_app(get_config, tool_name="pluralsight"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
