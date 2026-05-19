"""Browser session automation for Twopages."""
from cli_tools_shared.auth import BrowserAutomation


class TwopagesBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Twopages authentication."""

    SESSION_NAME = "twopages"
    LOGIN_URL = "https://twopagescurtains.com/"
    AUTH_CHECK_URL = "https://twopagescurtains.com/"
    AUTH_URL_PATTERN = r"/login"
