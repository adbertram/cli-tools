"""Browser session automation for Ubiquiti."""
from cli_tools_shared.auth import BrowserAutomation


class UbiquitiBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Ubiquiti authentication."""

    SESSION_NAME = "ubiquiti"
    LOGIN_URL = "https://creators.ui.com/"
    AUTH_CHECK_URL = "https://creators.ui.com/"
    AUTH_URL_PATTERN = r"/login"
