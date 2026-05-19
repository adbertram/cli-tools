"""Browser automation for MyFitnessPal.

Handles interactive login via persistent browser profiles (playwright CLI).
After login, the python-myfitnesspal library reads browser cookies directly.
"""
from cli_tools_shared.auth import BrowserAutomation

from .config import get_config


class MyFitnessPalBrowser(BrowserAutomation):
    """MyFitnessPal browser automation.

    Provides interactive login flow via the playwright CLI.
    The python-myfitnesspal library then reads the resulting
    cookies for API access.
    """

    SESSION_NAME = "fitnesspal"
    LOGIN_URL = "https://www.myfitnesspal.com/account/login"
    AUTH_CHECK_URL = "https://www.myfitnesspal.com/food/diary"
    AUTH_URL_PATTERN = r"/account/login"
    AUTH_COOKIE_PATTERNS = ["MFP_TOKEN", "user-id"]

    def __init__(self, config=None):
        config = config or get_config()
        super().__init__(config)
