"""Main entry point for PayPal CLI."""
from . import __version__
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

from .commands import payouts, transactions
from .config import get_config

app = create_app(name="paypal", help="CLI interface for PayPal API", version=__version__)

# Register shared auth + cache apps
register_commands(app, get_config, payouts, name="payouts", help="Manage batch payouts")
register_commands(app, get_config, transactions, name="transactions", help="Manage transaction reporting")
app.add_typer(create_auth_app(get_config, tool_name="paypal"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
