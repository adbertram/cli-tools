"""Browser session automation for ModelloTurbo."""
from cli_tools_shared.auth import BrowserAutomation


class ModelloTurboBrowser(BrowserAutomation):
    """BrowserAutomation hooks for ModelloTurbo authentication."""

    SESSION_NAME = "modello-turbo"
    LOGIN_URL = "https://modelloturbo.com/"
    AUTH_CHECK_URL = "https://modelloturbo.com/"
    AUTH_URL_PATTERN = r"/login"
