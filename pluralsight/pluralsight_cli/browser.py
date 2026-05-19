"""Browser session automation for Pluralsight."""
from cli_tools_shared.auth import BrowserAutomation


class PluralsightBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Pluralsight authentication."""

    SESSION_NAME = "pluralsight"
    LOGIN_URL = "https://www.pluralsight.com/affiliate"
    AUTH_CHECK_URL = "https://www.pluralsight.com/affiliate"
    AUTH_URL_PATTERN = r"/login"
