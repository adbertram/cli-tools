"""Main entry point for ShopGoodwill CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from .client import ClientError
from .config import get_config

app = create_app(
    name="shopgoodwill",
    help="CLI interface for ShopGoodwill",
    version=__version__,
)

# Register command modules
from .commands import auth, search
app.add_typer(auth.app, name="auth", help="Manage authentication")
register_commands(app, get_config, search, name="search", help="Search listings")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
