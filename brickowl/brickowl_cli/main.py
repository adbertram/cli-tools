"""Main entry point for Brickowl CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

from .config import get_config


def _test_handler(config):
    """Test Brickowl API credentials with a lightweight API call."""
    from .client import BrickowlClient

    client = BrickowlClient()
    client.get_user_details()
    return {"api_test": "passed", "method": "api_key"}


app = create_app(
    name="brickowl",
    help="CLI interface for Brickowl API",
    version=__version__,
)

# Register command modules
from .commands import order, inventory, catalog, user, messages, refund, coupon, quotes, issue

app.add_typer(
    create_auth_app(get_config, tool_name="brickowl", test_handler=_test_handler),
    name="auth",
    help="Manage Brickowl API authentication",
)
register_commands(app, get_config, order, name="order", help="Manage Brick Owl orders")
register_commands(app, get_config, inventory, name="inventory", help="Manage Brick Owl inventory")
register_commands(app, get_config, catalog, name="catalog", help="Browse the Brick Owl catalog")
register_commands(app, get_config, user, name="user", help="View Brick Owl user details")
register_commands(app, get_config, messages, name="messages", help="Manage Brick Owl messages")
register_commands(app, get_config, refund, name="refund", help="Manage Brick Owl refunds")
register_commands(app, get_config, coupon, name="coupon", help="Manage Brick Owl coupons")
register_commands(app, get_config, quotes, name="quotes", help="Manage Brick Owl quotes")
register_commands(app, get_config, issue, name="issue", help="Manage Brick Owl issue reports")

# Register shared cache app
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
