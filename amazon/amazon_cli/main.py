"""Main entry point for Amazon CLI."""

import typer

from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import print_error

from . import __version__
from . import commands
from .config import get_config


def _test_handler(config):
    browser = config.get_browser()
    try:
        result = browser.test_session()
        if result.get("authenticated"):
            return {"api_test": "passed"}
        return {"api_test": f"failed: {result.get('error', 'session not authenticated')}"}
    finally:
        browser.close()


app = create_app(name="amazon", help="Amazon order evidence lookup", version=__version__)
app.add_typer(
    create_auth_app(get_config, tool_name="amazon", test_handler=_test_handler),
    name="auth",
)
app.add_typer(create_cache_app(get_config), name="cache")
register_commands(app, get_config, commands, name="orders", help="Inspect Amazon order evidence")


def main():
    """Main entry point."""
    try:
        run_app(app)
    except ClientError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


if __name__ == "__main__":
    main()
