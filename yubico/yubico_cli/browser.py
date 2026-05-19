"""Browser session automation for Yubico."""
from cli_tools_shared.auth import BrowserAutomation


class YubicoBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Yubico authentication."""

    SESSION_NAME = "yubico"
    LOGIN_URL = "https://affiliate-program.amazon.com/"
    AUTH_CHECK_URL = "https://affiliate-program.amazon.com/"
    AUTH_URL_PATTERN = r"/login"
