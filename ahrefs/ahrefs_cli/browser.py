"""Browser session automation for Ahrefs."""

from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError


class AhrefsBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Ahrefs authentication."""

    SESSION_NAME = "ahrefs"
    LOGIN_URL = "https://app.ahrefs.com"
    AUTH_CHECK_URL = "https://app.ahrefs.com"
    AUTH_URL_PATTERN = r"/login|/user/login"
    AUTH_SUCCESS_URL = r"/dashboard"
    AUTH_COOKIE_PATTERNS = [r"^BSSESSID$"]
    AUTH_COOKIE_DOMAINS = ("ahrefs.com", "app.ahrefs.com")
    AUTH_SUCCESS_SELECTOR = ".user-menu, [data-testid='user-menu']"
    AUTOMATION_HEADED = True
