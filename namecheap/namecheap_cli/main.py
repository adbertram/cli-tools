"""Main entry point for Namecheap CLI."""
from . import __version__
from .config import get_config
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

app = create_app(name="namecheap", help="CLI interface for Namecheap (browser automation)", version=__version__)

# Register command modules
from .commands import auth, search

register_commands(app, get_config, search, name="search", help="Search namecheap")
app.add_typer(auth.app, name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
