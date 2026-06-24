"""Browser automation for Facebook CLI."""
from cli_tools_shared.auth import BrowserAutomation


class FacebookBrowser(BrowserAutomation):
    SESSION_NAME = "facebook"
    LOGIN_URL = "https://www.facebook.com/login"
    AUTH_CHECK_URL = "https://m.facebook.com/"
    AUTH_URL_PATTERN = r"/login"
    AUTH_COOKIE_PATTERNS = ["c_user"]  # c_user cookie exists when logged into Facebook
    MANUAL_LOGIN = True
