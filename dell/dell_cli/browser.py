"""Browser session automation for Dell."""
from cli_tools_shared.auth import BrowserAutomation


class DellBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Dell authentication."""

    SESSION_NAME = "dell"
    LOGIN_URL = "https://www.flexoffers.com/affiliate-programs/dell-home-home-office-affiliate-program/"
    AUTH_CHECK_URL = "https://www.flexoffers.com/affiliate-programs/dell-home-home-office-affiliate-program/"
    AUTH_URL_PATTERN = r"/login"
