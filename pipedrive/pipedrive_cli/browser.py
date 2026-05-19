"""Browser session automation for Pipedrive."""
from cli_tools_shared.auth import BrowserAutomation


class PipedriveBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Pipedrive authentication."""

    SESSION_NAME = "pipedrive"
    LOGIN_URL = "https://www.pipedrive.com/"
    AUTH_CHECK_URL = "https://www.pipedrive.com/"
    AUTH_URL_PATTERN = r"/login"
