"""Main entry point for Brickfreedom CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

from .client import ClientError
from .config import get_config


def _test_handler(config):
    """Test browser session by navigating to dashboard."""
    browser = config.get_browser()
    try:
        result = browser.test_session()
        if result.get("authenticated"):
            return {"api_test": "passed"}
        return {"api_test": f"failed: {result.get('error', 'session not authenticated')}"}
    finally:
        browser.close()


app = create_app(
    name="brickfreedom",
    help="CLI interface for Brickfreedom dashboard automation",
    version=__version__,
)

# Register command modules
from .commands import task, order
app.add_typer(
    create_auth_app(get_config, tool_name="brickfreedom", test_handler=_test_handler),
    name="auth",
)
app.add_typer(create_cache_app(get_config), name="cache")
register_commands(app, get_config, task, name="task", help="Manage dashboard tasks")
register_commands(app, get_config, order, name="order", help="Manage orders")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
