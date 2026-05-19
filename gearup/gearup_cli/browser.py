"""Browser session automation for Gearup."""
from cli_tools_shared.auth import BrowserAutomation


class GearupBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Gearup authentication."""

    SESSION_NAME = "gearup"
    LOGIN_URL = "https://www.gearupbooster.com"
    AUTH_CHECK_URL = "https://www.gearupbooster.com"
    AUTH_URL_PATTERN = r"/login"
