"""Main entry point for {{ServiceName}} CLI.

Auth commands are provided by cli_tools_shared.create_auth_app() — do NOT
create custom auth login/logout/status/test commands. The common package
handles the entire auth lifecycle including browser session management.
"""

import typer
from typing import Optional

from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app

from .client import ClientError
from .config import get_config


def _test_handler(config):
    """Test browser session by navigating to authenticated page.

    This is the ONLY browser-specific code in main.py.
    It's passed to create_auth_app() as the test_handler for `auth test`.
    AuthVerifier handles the actual auth status checking.

    Return shape: the returned dict is MERGED into the per-credential-type
    block in `auth status`/`auth test` output. It must contain `api_test`
    set to `"passed"` or `"failed: <reason>"`. Any additional fields
    (e.g., `email`, `user_id`) are embedded alongside. Do NOT return a
    top-level `authenticated` key — AuthVerifier owns that field.
    """
    browser = config.get_browser()
    try:
        browser.get_page(browser.AUTH_CHECK_URL)
        return {"api_test": "passed"}
    except Exception as e:
        return {"api_test": f"failed: {e}"}
    finally:
        browser.close()


app = typer.Typer(
    name="{{cli_name}}",
    help="CLI interface for {{ServiceName}} via browser automation",
    add_completion=True,
)

# Register standard command modules from cli_tools_shared
app.add_typer(
    create_auth_app(get_config, tool_name="{{cli_name}}", test_handler=_test_handler),
    name="auth",
)
app.add_typer(create_cache_app(get_config), name="cache")

# Register domain-specific command modules
# from .commands import items, orders
# app.add_typer(items.app, name="items", help="Manage items")
# app.add_typer(orders.app, name="orders", help="Manage orders")


@app.callback(invoke_without_command=True)
def callback(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", help="Show version and exit", is_eager=True
    ),
):
    """{{ServiceName}} CLI - Browser automation for {{ServiceName}}."""
    if version:
        from . import __version__
        typer.echo(f"{{cli_name}}-cli version {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


def main():
    """Main entry point."""
    try:
        app()
    except ClientError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(2)
    except KeyboardInterrupt:
        typer.echo("\nAborted!", err=True)
        raise typer.Exit(130)


if __name__ == "__main__":
    main()
