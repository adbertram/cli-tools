"""Browser session automation for Onspace."""
from cli_tools_shared.auth import BrowserAutomation


class OnspaceBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Onspace authentication."""

    SESSION_NAME = "onspace"
    LOGIN_URL = "https://www.onspace.ai/imp/ai-app-builder-free"
    AUTH_CHECK_URL = "https://www.onspace.ai/imp/ai-app-builder-free"
    AUTH_URL_PATTERN = r"/login"
