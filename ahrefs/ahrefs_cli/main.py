"""Main entry point for Ahrefs CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

app = create_app(
    name="ahrefs",
    help="CLI interface for Ahrefs (browser automation)",
    version=__version__,
)

from .config import get_config

# Register command modules
from .commands import auth, site_audit
app.add_typer(auth.app, name="auth", help="Manage Ahrefs authentication")
app.add_typer(create_cache_app(get_config), name="cache")
register_commands(app, get_config, site_audit, name="site-audit", help="Site audit operations")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
