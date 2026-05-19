"""Browser session automation for MicrosoftAdvertising."""
from cli_tools_shared.auth import BrowserAutomation


class MicrosoftAdvertisingBrowser(BrowserAutomation):
    """BrowserAutomation hooks for MicrosoftAdvertising authentication."""

    SESSION_NAME = "microsoft-advertising"
    LOGIN_URL = "https://signup.cj.com/member/signup/publisher/?cid=3065612"
    AUTH_CHECK_URL = "https://signup.cj.com/member/signup/publisher/?cid=3065612"
    AUTH_URL_PATTERN = r"/login"
