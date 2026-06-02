"""Main entry point for Doordash CLI."""
import warnings

warnings.filterwarnings("ignore", module="urllib3")

from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

from . import __version__
from .client import ClientError
from .commands import orders, stores
from .config import get_config

app = create_app(
    name="doordash",
    help="CLI interface for Doordash (browser automation)",
    version=__version__,
)
app.add_typer(create_auth_app(get_config, tool_name="doordash"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")
register_commands(app, get_config, orders, name="orders", help="Manage DoorDash orders")
register_commands(app, get_config, stores, name="stores", help="Browse available stores/restaurants")


def main():
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
