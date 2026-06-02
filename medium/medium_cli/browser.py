"""Browser automation for Medium."""

from cli_tools_shared.auth import BrowserAutomation


class MediumBrowser(BrowserAutomation):
    """Browser automation for Medium."""

    SESSION_NAME = "medium"
    LOGIN_URL = "https://medium.com/m/signin"
    AUTH_CHECK_URL = "https://medium.com/new-story"
    AUTH_URL_PATTERN = r"/m/signin|/m/signup|/m/register|/m/sign-in"
