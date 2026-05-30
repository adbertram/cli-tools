"""DoorDash browser automation."""
from cli_tools_shared.auth import WebwrightBrowserAutomation, BrowserAutomationError


class DoorDashBrowser(WebwrightBrowserAutomation):
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
    # DoorDash/Cloudflare accepts the real local Chrome CDP profile but rejects
    # Playwright's persistent Chrome-for-Testing profile for auth reuse.
    WEBWRIGHT_BROWSER_MODE = "local_cdp"
    WEBWRIGHT_LOCAL_CDP_URL = "http://127.0.0.1:9224"
    WEBWRIGHT_LOCAL_CDP_EXECUTABLE = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    WEBWRIGHT_LOCAL_CDP_NEW_PAGE = False


BrowserError = BrowserAutomationError
