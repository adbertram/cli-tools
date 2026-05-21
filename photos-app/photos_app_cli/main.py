"""Main entry point for photos-app CLI."""
import warnings

warnings.filterwarnings("ignore", module="urllib3")

from . import __version__
from .client import ClientError
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

from .config import get_config

app = create_app(name="photos-app", help="Query and export photos from macOS Photos library", version=__version__)

# Register command modules
from .commands import auth, photos, albums
register_commands(app, get_config, auth, name="auth", help="Manage authentication")
register_commands(app, get_config, photos, name="photos", help="List and download photos")
register_commands(app, get_config, albums, name="albums", help="List and create albums")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
