"""Browser session automation for Tunnelbear."""
from cli_tools_shared.auth import BrowserAutomation


class TunnelbearBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Tunnelbear authentication."""

    SESSION_NAME = "tunnelbear"
    LOGIN_URL = "https://www.tunnelbear.com/affiliate/"
    AUTH_CHECK_URL = "https://www.tunnelbear.com/affiliate/"
    AUTH_URL_PATTERN = r"/login"
