"""Browser session automation for AppyPie."""
from cli_tools_shared.auth import BrowserAutomation


class AppyPieBrowser(BrowserAutomation):
    """BrowserAutomation hooks for AppyPie authentication."""

    SESSION_NAME = "appy-pie"
    LOGIN_URL = "https://www.appypie.com/"
    AUTH_CHECK_URL = "https://www.appypie.com/"
    AUTH_URL_PATTERN = r"/login"
