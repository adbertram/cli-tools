"""Browser session automation for Measureup."""
from cli_tools_shared.auth import BrowserAutomation


class MeasureupBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Measureup authentication."""

    SESSION_NAME = "measureup"
    LOGIN_URL = "https://www.measureup.com/become-affiliate/"
    AUTH_CHECK_URL = "https://www.measureup.com/become-affiliate/"
    AUTH_URL_PATTERN = r"/login"
