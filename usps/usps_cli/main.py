"""Main entry point for USPS CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from .client import ClientError
from .config import get_config

app = create_app(
    name="usps",
    help="CLI interface for USPS Tracking API",
    version=__version__,
)

# Register command modules
from .commands import auth, tracking

app.add_typer(auth.app, name="auth", help="Manage USPS API authentication")
register_commands(app, get_config, tracking, name="tracking", help="Track USPS packages")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
