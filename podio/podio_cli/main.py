"""Main entry point for Podio CLI."""
import warnings

from . import __version__
from .client import ClientError
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

from .config import get_config

warnings.filterwarnings("ignore", module="urllib3")

# Create main Typer app
app = create_app(name="podio", help="CLI interface for Podio API - Manage apps, items, tasks, and more", version=__version__)


# Import and register command modules
# These will be imported as they're created
try:
    from .commands import item, app as app_cmd, task, space, org, auth, comment, webhook, conversation, file, webform
    register_commands(app, get_config, item, name="item", help="Manage Podio items")
    register_commands(app, get_config, app_cmd, name="app", help="Manage Podio applications")
    register_commands(app, get_config, task, name="task", help="Manage Podio tasks")
    register_commands(app, get_config, space, name="space", help="Manage Podio spaces")
    register_commands(app, get_config, org, name="org", help="Manage Podio organizations")
    app.add_typer(auth.app, name="auth", help="OAuth authentication utilities")
    register_commands(app, get_config, comment, name="comment", help="Manage Podio comments")
    register_commands(app, get_config, webhook, name="webhook", help="Manage Podio webhooks")
    register_commands(app, get_config, conversation, name="conversation", help="Manage Podio conversations")
    register_commands(app, get_config, file, name="file", help="Manage Podio files")
    register_commands(app, get_config, webform, name="webform", help="Manage Podio webforms")
    app.add_typer(create_cache_app(get_config), name="cache")
except ImportError:
    # Commands not yet implemented - will add as we build them
    pass


def main():
    """Main entry point for the CLI application."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
