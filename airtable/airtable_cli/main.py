"""Main entry point for Airtable CLI."""
from . import __version__
import warnings

warnings.filterwarnings("ignore", module="urllib3")

from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

app = create_app(
    name="airtable",
    help="CLI interface for Airtable API",
    version=__version__,
)

# Register shared auth commands
from cli_tools_shared.auth_commands import create_auth_app
from .config import get_config

app.add_typer(create_auth_app(get_config, tool_name="airtable"), name="auth", help="Manage Airtable API authentication")
app.add_typer(create_cache_app(get_config), name="cache")

# Register command modules
from .commands import fields, records, tables
register_commands(app, get_config, records, name="records", help="Manage Airtable records")
register_commands(app, get_config, fields, name="fields", help="Manage Airtable fields")
register_commands(app, get_config, tables, name="tables", help="Manage Airtable tables")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
