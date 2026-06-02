"""Browser automation for Apple."""

from cli_tools_shared.auth import BrowserAutomation


class AppleBrowser(BrowserAutomation):
    """Browser automation for Apple."""

    SESSION_NAME = "apple"
    LOGIN_URL = "https://reportaproblem.apple.com/?s=6"
    AUTH_CHECK_URL = "https://reportaproblem.apple.com/?s=6"
    AUTH_URL_PATTERN = r"/signin|/sign-in|/login"
    AUTH_COOKIE_PATTERNS = [r"myacinfo", r"selfserv_toru", r"dqsid"]
    LOGIN_TIMEOUT = 900
