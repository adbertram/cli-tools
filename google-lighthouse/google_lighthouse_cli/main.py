"""Main entry point for the Google Lighthouse CLI wrapper."""

from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.command_registry import register_commands

from .client import ClientError
from . import commands
from .config import get_config

app = create_app(
    name="google-lighthouse",
    help="Run and manage Google Lighthouse audits",
    version=__version__,
    cache_support=False,
)

register_commands(app, get_config, commands, name="audits", help="Manage Lighthouse audits")
app.add_typer(create_auth_app(get_config, tool_name="google-lighthouse"), name="auth")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
