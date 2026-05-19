"""Browser session automation for Popai."""
from cli_tools_shared.auth import BrowserAutomation


class PopaiBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Popai authentication."""

    SESSION_NAME = "popai"
    LOGIN_URL = "https://sheets.popai.pro"
    AUTH_CHECK_URL = "https://sheets.popai.pro"
    AUTH_URL_PATTERN = r"/login"
