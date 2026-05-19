"""Browser session automation for Bitport."""
from cli_tools_shared.auth import BrowserAutomation


class BitportBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Bitport authentication."""

    SESSION_NAME = "bitport"
    LOGIN_URL = "https://affiliate.bitport.io/"
    AUTH_CHECK_URL = "https://affiliate.bitport.io/"
    AUTH_URL_PATTERN = r"/login"
