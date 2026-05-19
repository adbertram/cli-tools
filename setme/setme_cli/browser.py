"""Browser session automation for Setme."""
from cli_tools_shared.auth import BrowserAutomation


class SetmeBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Setme authentication."""

    SESSION_NAME = "setme"
    LOGIN_URL = "https://www.setme.net/"
    AUTH_CHECK_URL = "https://www.setme.net/"
    AUTH_URL_PATTERN = r"/login"
