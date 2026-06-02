"""Main entry point for Raptive CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.command_registry import register_commands
from .client import ClientError
from .config import get_config

app = create_app(
    name="raptive",
    help="CLI interface for Raptive traffic and revenue data",
    version=__version__,
)

# Register command modules
from .commands import auth, dashboard, earnings, traffic

app.add_typer(auth.app, name="auth", help="Manage Raptive authentication")
register_commands(app, get_config, dashboard, name="dashboard", help="View dashboard metrics and summaries")
register_commands(app, get_config, earnings, name="earnings", help="View earnings and revenue data")
register_commands(app, get_config, traffic, name="traffic", help="View traffic and session data")

# Register common commands
from cli_tools_shared.cache_commands import create_cache_app

app.add_typer(create_cache_app(get_config), name="cache", help="Manage response cache")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
