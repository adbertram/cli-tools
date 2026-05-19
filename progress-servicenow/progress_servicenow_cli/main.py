"""Main entry point for Progress ServiceNow CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from cli_tools_shared.exceptions import ClientError

from .config import get_config

app = create_app(
    name="progress-servicenow",
    help="CLI interface for Progress ServiceNow Employee Center (browser automation)",
    version=__version__,
)

# Register command modules
from .commands import ticket, catalog
register_commands(app, get_config, ticket, name="ticket", help="Manage ServiceNow tickets")
register_commands(app, get_config, catalog, name="catalog", help="Browse the ServiceNow catalog")
app.add_typer(create_auth_app(get_config, tool_name="progress-servicenow"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
