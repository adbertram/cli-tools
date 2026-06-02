"""Main entry point for Globiflow CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from .client import ClientError
from .browser import AuthenticationRequired
from .config import get_config

app = create_app(
    name="globiflow",
    help="CLI interface for Globiflow (browser automation)",
    version=__version__,
)

# Register command modules
from .commands import search, flows, triggers
app.add_typer(create_auth_app(get_config, tool_name="globiflow"), name="auth")
register_commands(app, get_config, search, name="search", help="Search globiflow")
register_commands(app, get_config, flows, name="flows", help="Manage Globiflow flows")
register_commands(app, get_config, triggers, name="triggers", help="Manage Globiflow triggers")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app, error_types=(ClientError, AuthenticationRequired))


if __name__ == "__main__":
    main()
