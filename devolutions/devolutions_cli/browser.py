"""Browser session automation for Devolutions."""
from cli_tools_shared.auth import BrowserAutomation


class DevolutionsBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Devolutions authentication."""

    SESSION_NAME = "devolutions"
    LOGIN_URL = "https://devolutions.net/buy/affiliates/"
    AUTH_CHECK_URL = "https://devolutions.net/buy/affiliates/"
    AUTH_URL_PATTERN = r"/login"
