"""Main entry point for FreshBooks CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.command_registry import register_commands

from .config import get_config
from cli_tools_shared.cache_commands import create_cache_app

# Create main Typer app
app = create_app(
    name="freshbooks",
    help="CLI interface for FreshBooks accounting API",
    version=__version__,
)


# Import and register command modules
try:
    from .commands import auth
    app.add_typer(auth.app, name="auth", help="Manage authentication")
except ImportError:
    pass

app.add_typer(create_cache_app(get_config), name="cache", help="Manage CLI cache")

try:
    from .commands import invoice
    register_commands(app, get_config, invoice, name="invoice", help="Manage invoices")
except ImportError:
    pass

try:
    from .commands import customer
    register_commands(app, get_config, customer, name="customer", help="Manage customers/clients")
except ImportError:
    pass


def main():
    """Main entry point for the CLI application."""
    run_app(app)


if __name__ == "__main__":
    main()
