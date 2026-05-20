"""Main entry point for n8n CLI Tool Node Converter."""
from . import __version__
from .client import ClientError
from cli_tools_shared import create_app, create_auth_app, run_app
from cli_tools_shared.command_registry import register_commands
from .config import get_config

app = create_app(name="n8n-cli-tool-node-converter", help="Convert standardized CLI tools into n8n community node packages", version=__version__, cache_support=False)

# Register command modules
from .commands import tools, nodes

app.add_typer(
    create_auth_app(get_config, tool_name="n8n-cli-tool-node-converter"),
    name="auth",
    help="Manage converter configuration",
)
register_commands(app, get_config, tools, name="tools", help="List and inspect available CLI tools")
register_commands(app, get_config, nodes, name="nodes", help="Generate and manage n8n node packages")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
