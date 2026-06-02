"""Main entry point for Medium CLI."""

from __future__ import annotations

import re

from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

from . import __version__
from .commands import posts
from .config import get_config

COMPOSER_TIMEOUT_MS = 60000


def _test_handler(config):
    """Verify that the saved browser session can load Medium's composer."""
    browser = config.get_browser()
    try:
        page = browser.get_page(browser.AUTH_CHECK_URL)
        if re.search(browser.AUTH_URL_PATTERN, page.url):
            return {"api_test": f"failed: redirected to {page.url}"}
        page.wait_for_selector('[contenteditable="true"]', timeout=COMPOSER_TIMEOUT_MS)
        return {"api_test": "passed", "editor_url": page.url}
    except Exception as exc:
        return {"api_test": f"failed: {exc}"}
    finally:
        browser.close()


app = create_app(
    name="medium",
    help="Create Medium drafts through Medium's web composer",
    version=__version__,
)
app.add_typer(
    create_auth_app(get_config, tool_name="medium", test_handler=_test_handler),
    name="auth",
    help="Manage Medium browser-session authentication",
)
app.add_typer(create_cache_app(get_config), name="cache", help="Manage cached Medium responses")
register_commands(
    app,
    get_config,
    posts,
    name="posts",
    help="Create Medium drafts",
    cli_name="medium",
)


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
