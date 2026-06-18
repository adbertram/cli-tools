"""Main entry point for WP Engine CLI."""

from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.command_registry import register_commands

from . import __version__
from .commands import accounts, api, cache, environments, sftp, sites, ssh
from .config import get_config

app = create_app(
    name="wpengine",
    help="CLI interface for WP Engine Hosting Platform API",
    version=__version__,
)

app.add_typer(create_auth_app(get_config, tool_name="wpengine"), name="auth")
register_commands(app, get_config, api, name="api", help="Inspect the WP Engine API")
register_commands(app, get_config, accounts, name="accounts", help="List and inspect WP Engine accounts")
register_commands(app, get_config, sites, name="sites", help="List and inspect WP Engine sites")
register_commands(app, get_config, environments, name="environments", help="List and inspect WP Engine environments")
register_commands(app, get_config, cache, name="cache", help="Manage WP Engine environment caches")
register_commands(app, get_config, ssh, name="ssh", help="Build SSH connection details and manage SSH keys")
register_commands(app, get_config, sftp, name="sftp", help="Build SFTP connection details")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
