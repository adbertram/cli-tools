"""Browser session automation for Rewarx."""
from cli_tools_shared.auth import BrowserAutomation


class RewarxBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Rewarx authentication."""

    SESSION_NAME = "rewarx"
    LOGIN_URL = "https://www.rewarx.com/"
    AUTH_CHECK_URL = "https://www.rewarx.com/"
    AUTH_URL_PATTERN = r"/login"
