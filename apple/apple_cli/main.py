"""Main entry point for Apple CLI."""

import typer

from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import print_error

from . import __version__
from .auth_capture import apple_browser_login
from .client import probe_purchase_search_context
from . import commands
from .config import get_config


def _test_handler(config):
    browser = config.get_browser()
    try:
        result = browser.test_session()
        if result.get("authenticated"):
            probe_purchase_search_context(config)
            return {"api_test": "passed"}
        return {"api_test": f"failed: {result.get('error', 'session not authenticated')}"}
    except ClientError as exc:
        return {"api_test": f"failed: {exc}"}
    finally:
        browser.close()


app = create_app(name="apple", help="Apple purchase and subscription history lookup", version=__version__)
app.add_typer(
    create_auth_app(get_config, tool_name="apple", login_handler=apple_browser_login, test_handler=_test_handler),
    name="auth",
)
app.add_typer(create_cache_app(get_config), name="cache")
register_commands(app, get_config, commands, name="purchases", help="Inspect Apple purchase and subscription history")


def main():
    """Main entry point."""
    try:
        run_app(app)
    except ClientError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


if __name__ == "__main__":
    main()
