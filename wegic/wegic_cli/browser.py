"""Browser session automation for Wegic."""
from cli_tools_shared.auth import BrowserAutomation


class WegicBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Wegic authentication."""

    SESSION_NAME = "wegic"
    LOGIN_URL = "https://wegic.ai/"
    AUTH_CHECK_URL = "https://wegic.ai/"
    AUTH_URL_PATTERN = r"/login"
