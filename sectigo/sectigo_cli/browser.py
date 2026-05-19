"""Browser session automation for Sectigo."""
from cli_tools_shared.auth import BrowserAutomation


class SectigoBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Sectigo authentication."""

    SESSION_NAME = "sectigo"
    LOGIN_URL = "https://sectigostore.com/partner/affiliate"
    AUTH_CHECK_URL = "https://sectigostore.com/partner/affiliate"
    AUTH_URL_PATTERN = r"/login"
