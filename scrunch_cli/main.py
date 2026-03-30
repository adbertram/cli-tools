"""Main entry point for Scrunch CLI."""
from . import __version__
from .config import get_config
from cli_tools_common import create_app, run_app
from cli_tools_common.auth_commands import create_auth_app
from cli_tools_common.cache_commands import create_cache_app
from cli_tools_common.profiles_commands import create_profiles_app

app = create_app(name="scrunch", help="CLI interface for Scrunch API", version=__version__)

# Register command modules
from .commands import items
app.add_typer(items.app, name="items", help="Manage scrunch items")

# Register shared apps
app.add_typer(create_auth_app(get_config, tool_name="scrunch"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")
app.add_typer(create_profiles_app(get_config), name="profiles")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
