"""Browser session automation for HideMe."""
from cli_tools_shared.auth import BrowserAutomation


class HideMeBrowser(BrowserAutomation):
    """BrowserAutomation hooks for HideMe authentication."""

    SESSION_NAME = "hide-me"
    LOGIN_URL = "https://hide.me/en/affiliate"
    AUTH_CHECK_URL = "https://hide.me/en/affiliate"
    AUTH_URL_PATTERN = r"/login"
