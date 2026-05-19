"""Browser session automation for Techsmith."""
from cli_tools_shared.auth import BrowserAutomation


class TechsmithBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Techsmith authentication."""

    SESSION_NAME = "techsmith"
    LOGIN_URL = "https://www.techsmith.com/resources/affiliate-partners/"
    AUTH_CHECK_URL = "https://www.techsmith.com/resources/affiliate-partners/"
    AUTH_URL_PATTERN = r"/login"
