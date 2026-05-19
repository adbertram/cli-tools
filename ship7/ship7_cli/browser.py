"""Browser session automation for Ship7."""
from cli_tools_shared.auth import BrowserAutomation


class Ship7Browser(BrowserAutomation):
    """BrowserAutomation hooks for Ship7 authentication."""

    SESSION_NAME = "ship7"
    LOGIN_URL = "https://www.ship7.com"
    AUTH_CHECK_URL = "https://www.ship7.com"
    AUTH_URL_PATTERN = r"/login"
