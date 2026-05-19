"""Main entry point for ClickBank CLI."""
from . import __version__
from .config import get_config
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

app = create_app(name="clickbank", help="CLI interface for ClickBank API", version=__version__)

# Register command modules
from .commands import marketplace, orders, products, quickstats
register_commands(app, get_config, orders, name="orders", help="Work with ClickBank orders")
register_commands(app, get_config, products, name="products", help="Work with ClickBank products")
register_commands(app, get_config, quickstats, name="quickstats", help="Work with ClickBank quickstats")
register_commands(
    app,
    get_config,
    marketplace,
    name="marketplace",
    help="Search the public ClickBank affiliate marketplace",
)

# Register shared apps
app.add_typer(create_auth_app(get_config, tool_name="clickbank"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
