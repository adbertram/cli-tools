"""Browser-session integration for YouTube web-only channel actions."""

from cli_tools_shared.auth import BrowserAutomation


class YouTubeBrowser(BrowserAutomation):
    """Declarative browser hooks for YouTube channel-page auth."""

    SESSION_NAME = "youtube"
    LOGIN_URL = "https://www.youtube.com/"
    AUTH_CHECK_URL = "https://www.youtube.com/"
    AUTH_URL_PATTERN = r"accounts\.google\.com|ServiceLogin|signin"
    AUTH_SUCCESS_SELECTOR = "button#avatar-btn"
