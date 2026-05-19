"""Browser session automation for Dropxl."""
from cli_tools_shared.auth import BrowserAutomation


class DropxlBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Dropxl authentication."""

    SESSION_NAME = "dropxl"
    LOGIN_URL = "https://www.dropxl.com/homepage.html"
    AUTH_CHECK_URL = "https://www.dropxl.com/homepage.html"
    AUTH_URL_PATTERN = r"/login"
