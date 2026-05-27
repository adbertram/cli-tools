"""DoorDash browser automation."""
from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError


class DoorDashBrowser(BrowserAutomation):
    SESSION_NAME = "doordash"
    LOGIN_URL = "https://www.doordash.com"
    # `/home` reliably hydrates consumerId for signed-in sessions. The legacy
    # `/consumer/orders` guest flow can render a soft-error page and flap auth
    # checks even while the account is otherwise usable.
    AUTH_CHECK_URL = "https://www.doordash.com/home"
    AUTH_URL_PATTERN = r"identity\.doordash\.com|/login|/consumer/login|/sign-in"
    AUTH_STORAGE_KEY = "consumerId"
    # Cloudflare blocks headless Chrome on checkout; reorder runs headed.
    AUTOMATION_HEADED = True


BrowserError = BrowserAutomationError
