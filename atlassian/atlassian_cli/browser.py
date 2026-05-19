"""Browser session automation for Atlassian."""
from cli_tools_shared.auth import BrowserAutomation


class AtlassianBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Atlassian authentication."""

    SESSION_NAME = "atlassian"
    LOGIN_URL = "https://www.flexoffers.com/affiliate-programs/atlassian-affiliate-program/"
    AUTH_CHECK_URL = "https://www.flexoffers.com/affiliate-programs/atlassian-affiliate-program/"
    AUTH_URL_PATTERN = r"/login"
