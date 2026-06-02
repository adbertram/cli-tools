"""Browser automation for MyFitnessPal.

Handles interactive login via persistent browser profiles (playwright CLI).
After login, the python-myfitnesspal library reads browser cookies directly.
"""
from cli_tools_shared.auth import BrowserAutomation


class MyFitnessPalBrowser(BrowserAutomation):
    """MyFitnessPal browser automation.

    Provides interactive login flow via the playwright CLI.
    The python-myfitnesspal library then reads the resulting
    cookies for API access.
    """

    SESSION_NAME = "fitnesspal"
    LOGIN_URL = "https://www.myfitnesspal.com/account/login"
    AUTH_CHECK_URL = "https://www.myfitnesspal.com/"
    AUTH_URL_PATTERN = r"/account/login|/user/login"
    AUTH_COOKIE_PATTERNS = [r"^__Secure-next-auth\.session-token$"]
