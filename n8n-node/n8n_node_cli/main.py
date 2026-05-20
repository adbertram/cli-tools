"""Main entry point for n8n Node."""
from . import __version__
from .client import ClientError
from .config import get_config
from cli_tools_shared import create_app, create_auth_app, run_app
from cli_tools_shared.cache_commands import create_cache_app

app = create_app(name="n8n-node", help="Manage n8n community node packages - convert CLI tools, generate, and inspect", version=__version__)

# Register command modules
from .commands import tools, nodes, convert, test, deploy, credentials, logs

app.add_typer(tools.app, name="tools", help="List and inspect available CLI tools")
app.add_typer(nodes.app, name="nodes", help="List and inspect generated n8n node packages")
app.add_typer(credentials.app, name="credentials", help="Manage n8n credentials on the server")
app.add_typer(logs.app, name="logs", help="Query n8n logs, events, and execution history")
app.add_typer(create_auth_app(get_config, tool_name="n8n-node"), name="auth", help="Manage n8n-node authentication")
app.add_typer(create_cache_app(get_config), name="cache")
app.command("convert-cli-tool")(convert.convert_cli_tool)
app.command("test")(test.test_node)
app.command("deploy")(deploy.deploy_node)


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
