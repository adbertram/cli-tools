"""Browser session automation for Trycrush."""
from cli_tools_shared.auth import BrowserAutomation


class TrycrushBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Trycrush authentication."""

    SESSION_NAME = "trycrush"
    LOGIN_URL = "https://trycrush.ai"
    AUTH_CHECK_URL = "https://trycrush.ai"
    AUTH_URL_PATTERN = r"/login"
