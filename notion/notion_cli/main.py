"""Main entry point for Notion CLI."""
import warnings

warnings.filterwarnings("ignore", module="urllib3")

from . import __version__
from .client import ClientError
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from .config import get_config

# Create main Typer app
app = create_app(name="notion", help="CLI interface for Notion API with database query filtering", version=__version__)


# Import and register command modules
try:
    from .commands import auth
    app.add_typer(auth.app, name="auth", help="Manage authentication")
except ImportError:
    pass

try:
    from .commands import database
    register_commands(app, get_config, database, name="database", help="Query and manage databases")
except ImportError:
    pass

try:
    from .commands import field
    register_commands(app, get_config, field, name="field", help="Manage database field schemas")
except ImportError:
    pass

try:
    from .commands import page
    register_commands(app, get_config, page, name="pages", help="Query and manage standalone pages")
except ImportError:
    pass

try:
    from .commands import comments
    register_commands(app, get_config, comments, name="comments", help="Manage comments on pages and blocks")
except ImportError:
    pass

try:
    app.add_typer(create_cache_app(get_config), name="cache")
except ImportError:
    pass


def main():
    """Main entry point for the CLI application."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
