"""Main entry point for Toloka CLI."""
import warnings

warnings.filterwarnings("ignore", module="urllib3")

from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

from . import __version__, commands
from .client import ClientError
from .config import get_config

app = create_app(
    name="toloka",
    help="CLI interface for Toloka (gig worker portal automation)",
    version=__version__,
)
app.add_typer(create_auth_app(get_config, tool_name="toloka"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")
register_commands(app, get_config, commands, name="tasks", help="Browse and apply to Toloka tasks")


def main():
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
