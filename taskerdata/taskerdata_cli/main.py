"""Main entry point for TaskerData CLI."""

from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from cli_tools_shared.exceptions import ClientError

from . import __version__, commands
from .config import get_config

app = create_app(
    name="taskerdata",
    help="TaskerData gig worker portal automation (browser automation)",
    version=__version__,
)
app.add_typer(create_auth_app(get_config, tool_name="taskerdata"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")
register_commands(app, get_config, commands, name="tasks", help="Manage TaskerData worker tasks")


def main():
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
