"""Browser automation class for Nextdoor CLI."""

from cli_tools_shared.auth import BrowserAutomation


class NextdoorBrowser(BrowserAutomation):
    """Browser automation for Nextdoor."""
    LOGIN_URL = "https://nextdoor.com/login/"
    AUTH_CHECK_URL = "https://nextdoor.com/"
    AUTH_URL_PATTERN = "nextdoor.com"
    SESSION_NAME = "nextdoor"
    AUTH_COOKIE_PATTERNS = ["ndp_session_id"]
