"""Authentication commands for Slack CLI.

Uses create_auth_app() from cli_tools_shared for standard auth commands.
The login_handler opens Chrome, user logs into Slack, token is captured
from localStorage and saved to the profile's .env file.
"""
from cli_tools_shared import create_auth_app
from cli_tools_shared.output import print_success, print_error, print_info

from ..config import get_config
from ..browser import SlackBrowser


def slack_login_handler(config, force: bool):
    """Custom login handler: opens Chrome, user logs into Slack, token is captured."""
    print_info("Opening Chrome for Slack authentication...")
    print_info("Log into Slack in the browser window. The token will be captured automatically.")

    browser = SlackBrowser(config)
    try:
        result = browser.login(force=force)
        if result.get("success"):
            print_success("Slack session authenticated. Token saved to profile.")
        else:
            print_error(f"Browser auth failed: {result.get('message', 'Unknown error')}")
            raise SystemExit(1)
    finally:
        browser.close()


# Create the auth app with all standard commands (login, logout, status, test, refresh)
# The test command uses config.test_connection() which is defined on Config
app = create_auth_app(get_config, tool_name="slack", login_handler=slack_login_handler)
