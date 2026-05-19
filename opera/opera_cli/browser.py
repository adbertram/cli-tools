"""Browser session automation for Opera."""
from cli_tools_shared.auth import BrowserAutomation


class OperaBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Opera authentication."""

    SESSION_NAME = "opera"
    LOGIN_URL = "https://www.opera.com/opera/affiliate"
    AUTH_CHECK_URL = "https://www.opera.com/opera/affiliate"
    AUTH_URL_PATTERN = r"/login"
