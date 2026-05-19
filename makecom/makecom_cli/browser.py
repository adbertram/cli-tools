"""Browser session automation for Make.com."""
from cli_tools_shared.auth import BrowserAutomation


class MakecomBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Make.com authentication."""

    SESSION_NAME = "makecom"
    LOGIN_URL = "https://www.make.com/en/login"
    AUTH_CHECK_URL = "https://www.make.com/en/affiliate"
    AUTH_URL_PATTERN = r"/login"
