"""Browser session automation for Quartile."""
from cli_tools_shared.auth import BrowserAutomation


class QuartileBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Quartile authentication."""

    SESSION_NAME = "quartile"
    LOGIN_URL = "https://www.quartile.com/"
    AUTH_CHECK_URL = "https://www.quartile.com/"
    AUTH_URL_PATTERN = r"/login"
