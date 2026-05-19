"""DoorDash browser automation."""
from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError


class DoorDashBrowser(BrowserAutomation):
    SESSION_NAME = "doordash"
    LOGIN_URL = "https://www.doordash.com"
    AUTH_CHECK_URL = "https://www.doordash.com/consumer/orders"
    AUTH_URL_PATTERN = r"identity\.doordash\.com|/login|/consumer/login|/sign-in"
    AUTH_COOKIE_PATTERNS = [r"dd.*session", r"session.*", r"__cf_bm"]
    # Cloudflare blocks headless Chrome on checkout; reorder runs headed.
    AUTOMATION_HEADED = True


BrowserError = BrowserAutomationError
