"""Browser automation hooks for X Developer Console."""

from cli_tools_shared.auth import BrowserAutomation


class XBrowser(BrowserAutomation):
    """Declarative browser automation for X Developer Console."""

    SESSION_NAME = "x"
    LOGIN_URL = "https://console.x.com/"
    AUTH_CHECK_URL = "https://console.x.com/"
    AUTH_URL_PATTERN = r"x\.com/i/.*login|/login"
    AUTH_COOKIE_PATTERNS = [r"^auth_token$"]
    AUTH_LOGIN_FORM_SELECTOR = 'input[name="password"], input[name="text"]'
    MANUAL_LOGIN = True
