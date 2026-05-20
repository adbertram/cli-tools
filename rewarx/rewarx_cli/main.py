"""Main entry point for Rewarx CLI."""
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app

from . import __version__
from .commands import app as program_app
from .config import get_config

app = create_app(
    name="rewarx",
    help="CLI interface for the Rewarx affiliate program",
    version=__version__,
)
app.add_typer(program_app, name="program")
app.add_typer(create_auth_app(get_config, tool_name="rewarx"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
