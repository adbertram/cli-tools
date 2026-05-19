"""Browser session automation for Hp."""
from cli_tools_shared.auth import BrowserAutomation


class HpBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Hp authentication."""

    SESSION_NAME = "hp"
    LOGIN_URL = "https://www.hp.com/us-en/shop/cv/affiliate-program"
    AUTH_CHECK_URL = "https://www.hp.com/us-en/shop/cv/affiliate-program"
    AUTH_URL_PATTERN = r"/login"
