"""Main entry point for Instacart CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from .client import ClientError
from .config import get_config

app = create_app(
    name="instacart",
    help="CLI interface for Instacart API",
    version=__version__,
)

# Register command modules
from .commands import auth, cart, orders, user
app.add_typer(auth.app, name="auth", help="Manage Instacart authentication")
register_commands(app, get_config, cart, name="cart", help="Manage shopping cart")
register_commands(app, get_config, orders, name="orders", help="Manage Instacart orders")
register_commands(app, get_config, user, name="user", help="Manage user account")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
