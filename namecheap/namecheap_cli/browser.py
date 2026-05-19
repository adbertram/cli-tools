"""Browser session automation for Namecheap."""
from cli_tools_shared.auth import BrowserAutomation


class NamecheapBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Namecheap authentication."""

    SESSION_NAME = "namecheap"
    LOGIN_URL = "https://www.namecheap.com/affiliates/"
    AUTH_CHECK_URL = "https://www.namecheap.com/affiliates/"
    AUTH_URL_PATTERN = r"/login"
