"""Browser session automation for Reclaim."""
from cli_tools_shared.auth import BrowserAutomation


class ReclaimBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Reclaim authentication."""

    SESSION_NAME = "reclaim"
    LOGIN_URL = "https://reclaim.ai/"
    AUTH_CHECK_URL = "https://reclaim.ai/"
    AUTH_URL_PATTERN = r"/login"
