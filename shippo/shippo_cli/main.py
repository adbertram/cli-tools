"""Main entry point for Shippo CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.exceptions import ClientError

app = create_app(
    name="shippo",
    help="CLI interface for Shippo shipping API - Create USPS labels, compare rates, track packages",
    version=__version__,
)

# Register shared auth commands
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.command_registry import register_commands
from .config import get_config

app.add_typer(create_auth_app(get_config, tool_name="shippo"), name="auth", help="Manage Shippo API authentication")
app.add_typer(create_cache_app(get_config), name="cache", help="Manage CLI cache")

# Register command modules
from .commands import addresses, shipments, rates, labels, tracking, carriers

register_commands(app, get_config, addresses, name="addresses", help="Manage saved addresses")
register_commands(app, get_config, shipments, name="shipments", help="Create shipments, view rates")
register_commands(app, get_config, rates, name="rates", help="View and compare shipping rates")
register_commands(app, get_config, labels, name="labels", help="Purchase and manage shipping labels")
register_commands(app, get_config, tracking, name="tracking", help="Track shipments")
register_commands(app, get_config, carriers, name="carriers", help="Manage carrier accounts")
def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
