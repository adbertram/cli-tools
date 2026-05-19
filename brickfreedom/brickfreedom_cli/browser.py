"""Browser automation for Brickfreedom dashboard."""

from cli_tools_shared.auth import BrowserAutomation


class BrickfreedomBrowser(BrowserAutomation):
    """Browser automation for Brickfreedom dashboard."""

    SESSION_NAME = "brickfreedom"
    LOGIN_URL = "https://brickfreedom.com/login"
    AUTH_CHECK_URL = "https://brickfreedom.com/dashboard"
    AUTH_URL_PATTERN = r"/login|/register"
    AUTH_SUCCESS_SELECTOR = 'h2.text-xl'
