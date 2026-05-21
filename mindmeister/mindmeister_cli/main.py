import warnings

warnings.filterwarnings("ignore", module="urllib3")

"""Main entry point for Mindmeister CLI."""
from . import __version__
from .client import ClientError
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

app = create_app(name="mindmeister", help="CLI interface for Mindmeister API", version=__version__)

# Register command modules
from .commands import auth, maps, ideas
from .config import get_config

app.add_typer(auth.app, name="auth", help="Manage MindMeister authentication")
register_commands(app, get_config, maps, name="maps", help="Manage MindMeister mind maps")
register_commands(app, get_config, ideas, name="ideas", help="Manage ideas/nodes in mind maps")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
