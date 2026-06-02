"""Main entry point for OneDrive CLI."""
import warnings

warnings.filterwarnings("ignore", module="urllib3")

from . import __version__
from .client import ClientError
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

app = create_app(name="onedrive", help="OneDrive for Business CLI via Microsoft Graph API", version=__version__)

# Register command modules
from .commands import auth, drives, folders, items, link
from .config import get_config

app.add_typer(auth.app, name="auth", help="Manage authentication via Azure CLI")
register_commands(app, get_config, drives, name="drives", help="Manage OneDrive drives")
register_commands(app, get_config, folders, name="folders", help="Manage folders")
register_commands(app, get_config, items, name="items", help="Manage files and folders")
register_commands(app, get_config, link, name="link", help="Manage sharing links")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
