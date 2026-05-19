"""Main entry point for Moz CLI."""
from . import __version__
from .client import ClientError
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

app = create_app(name="moz", help="CLI interface for Moz API", version=__version__)

# Register command modules
from .commands import auth, keywords
from .config import get_config

app.add_typer(auth.app, name="auth", help="Manage Moz API authentication")
register_commands(app, get_config, keywords, name="keywords", help="Keyword research and analysis")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
