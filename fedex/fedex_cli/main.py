"""Main entry point for Fedex CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.command_registry import register_commands
from .client import ClientError
from .config import get_config

app = create_app(
    name="fedex",
    help="CLI interface for Fedex API",
    version=__version__,
)

# Register command modules
from .commands import auth, pickup
from cli_tools_shared.cache_commands import create_cache_app
app.add_typer(auth.app, name="auth", help="Manage Fedex API authentication")
app.add_typer(create_cache_app(get_config), name="cache", help="Manage CLI cache")
register_commands(app, get_config, pickup, name="pickup", help="Schedule and manage FedEx pickups")
def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
