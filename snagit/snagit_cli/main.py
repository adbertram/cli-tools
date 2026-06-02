"""Main entry point for Snagit CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.command_registry import register_commands
from .client import ClientError
from .config import get_config

app = create_app(
    name="snagit",
    help="CLI for managing Snagit capture files (.snagx format)",
    version=__version__,
    cache_support=False,
)

# Register command modules
from . import commands as capture
register_commands(app, get_config, capture, name="capture", help="Manage Snagit capture files")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
