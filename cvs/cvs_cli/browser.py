"""Browser automation for CVS CLI."""
from cli_tools_shared.auth import BrowserAutomation


class CvsBrowser(BrowserAutomation):
    SESSION_NAME = "cvs"
    LOGIN_URL = "https://www.cvs.com/account-login/look-up"
    AUTH_CHECK_URL = "https://www.cvs.com/account/profile"
    AUTH_URL_PATTERN = r"/account-login"
    AUTH_COOKIE_PATTERNS = ["access_token"]
