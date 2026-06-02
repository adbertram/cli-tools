"""Main entry point for AmazonAssociates CLI."""
import warnings

from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

from . import __version__
from . import commands
from .config import get_config

warnings.filterwarnings("ignore", module="urllib3")

app = create_app(
    name="amazon-associates",
    help="CLI interface for the AmazonAssociates affiliate program",
    version=__version__,
)
register_commands(app, get_config, commands, name="program", help="Show program metadata")
app.add_typer(create_auth_app(get_config, tool_name="amazon-associates"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
