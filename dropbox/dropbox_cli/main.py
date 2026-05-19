"""Main entry point for Dropbox CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from .client import ClientError
from .config import get_config

app = create_app(
    name="dropbox",
    help="CLI interface for Dropbox API",
    version=__version__,
)

# Register command modules
from .commands import auth, files, folders, account, sharing

app.add_typer(auth.app, name="auth", help="Manage Dropbox authentication")
app.add_typer(create_cache_app(get_config), name="cache")
register_commands(app, get_config, files, name="files", help="Manage files and folders")
register_commands(app, get_config, folders, name="folders", help="Manage folders")
register_commands(app, get_config, account, name="account", help="View account information")
register_commands(app, get_config, sharing, name="sharing", help="Work with shared links and folders")
def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
