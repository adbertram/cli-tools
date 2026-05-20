"""Main entry point for Udemy CLI."""
from . import __version__
from .config import get_config
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

app = create_app(name="udemy", help="Udemy Instructor API CLI", version=__version__)

# Register command modules
from . import commands as courses
register_commands(app, get_config, courses, name="courses", help="Manage instructor courses", cli_name="udemy")

# Register shared apps
app.add_typer(create_auth_app(get_config, tool_name="udemy"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
