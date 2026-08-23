"""Main entry point for Upwork CLI."""

from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

from . import __version__
from .client import ClientError
from .config import get_config

from .commands import jobs, profile

app = create_app(name="upwork", help="CLI interface for Upwork", version=__version__)


# No explicit test_handler: create_auth_app auto-detects Config.test_connection()
# and AuthVerifier applies it as the live check for the OAuth credential type
# (a real lightweight GraphQL call). The browser_session credential is
# intentionally NOT live-tested here — Upwork's Cloudflare challenge blocks
# non-headed automation, so auth status must not launch a browser. AuthVerifier
# only calls the API test for the browser type when
# BROWSER_SESSION_REQUIRES_API_TEST is set, which this CLI deliberately leaves off.
app.add_typer(
    create_auth_app(get_config, tool_name="upwork"),
    name="auth",
)
app.add_typer(create_cache_app(get_config), name="cache")
register_commands(
    app,
    get_config,
    profile,
    name="profile",
    help="Read and update freelancer profile attributes",
)
register_commands(
    app,
    get_config,
    jobs,
    name="jobs",
    help="Search Upwork marketplace job postings",
)


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
