"""Main entry point for n8n CLI."""
from . import __version__
from .client import ClientError
from .config import get_config
from cli_tools_shared import create_app, run_app, create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

app = create_app(name="n8n", help="Manage n8n server - workflows, nodes, executions, credentials, data tables, and logs", version=__version__)

# Standard auth from cli-tools-shared
app.add_typer(create_auth_app(get_config, tool_name='n8n'), name='auth', help="Manage n8n authentication")
app.add_typer(create_cache_app(get_config), name="cache")

# Register command modules with runtime credential checks
from .commands import nodes, credentials, data_tables, executions, server, workflows

register_commands(app, get_config, workflows, name="workflows", help="Manage n8n workflows")
register_commands(app, get_config, nodes, name="nodes", help="Manage n8n node packages")
register_commands(app, get_config, credentials, name="credentials", help="Manage n8n credentials on the server")
register_commands(app, get_config, data_tables, name="data-tables", help="Manage n8n Data Tables")
register_commands(app, get_config, executions, name="executions", help="Query workflow executions and events")
register_commands(app, get_config, server, name="server", help="Manage the n8n server")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
