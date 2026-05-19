"""Browser session automation for Lenovo."""
from cli_tools_shared.auth import BrowserAutomation


class LenovoBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Lenovo authentication."""

    SESSION_NAME = "lenovo"
    LOGIN_URL = "https://www.lenovo.com/us/en/affiliate-program/resources/index.html"
    AUTH_CHECK_URL = "https://www.lenovo.com/us/en/affiliate-program/resources/index.html"
    AUTH_URL_PATTERN = r"/login"
