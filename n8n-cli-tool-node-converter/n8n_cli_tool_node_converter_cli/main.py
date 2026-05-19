"""Main entry point for n8n CLI Tool Node Converter."""
from . import __version__
from .client import ClientError
from cli_tools_shared import create_app, run_app

app = create_app(name="n8n-cli-tool-node-converter", help="Convert standardized CLI tools into n8n community node packages", version=__version__, cache_support=False)

# Register command modules
from .commands import tools, nodes

app.add_typer(tools.app, name="tools", help="List and inspect available CLI tools")
app.add_typer(nodes.app, name="nodes", help="Generate and manage n8n node packages")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
