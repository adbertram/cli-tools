"""Browser session automation for Plusmetrica."""
from cli_tools_shared.auth import BrowserAutomation


class PlusmetricaBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Plusmetrica authentication."""

    SESSION_NAME = "plusmetrica"
    LOGIN_URL = "https://www.plusmetrica.com/"
    AUTH_CHECK_URL = "https://www.plusmetrica.com/"
    AUTH_URL_PATTERN = r"/login"
