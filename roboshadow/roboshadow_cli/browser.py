"""Browser session automation for Roboshadow."""
from cli_tools_shared.auth import BrowserAutomation


class RoboshadowBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Roboshadow authentication."""

    SESSION_NAME = "roboshadow"
    LOGIN_URL = "https://www.roboshadow.com/"
    AUTH_CHECK_URL = "https://www.roboshadow.com/"
    AUTH_URL_PATTERN = r"/login"
