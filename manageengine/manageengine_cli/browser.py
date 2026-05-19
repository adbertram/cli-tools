"""Browser session automation for Manageengine."""
from cli_tools_shared.auth import BrowserAutomation


class ManageengineBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Manageengine authentication."""

    SESSION_NAME = "manageengine"
    LOGIN_URL = "https://www.manageengine.com/affiliate/signup.html"
    AUTH_CHECK_URL = "https://www.manageengine.com/affiliate/signup.html"
    AUTH_URL_PATTERN = r"/login"
