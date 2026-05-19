"""Browser session automation for RevoUninstaller."""
from cli_tools_shared.auth import BrowserAutomation


class RevoUninstallerBrowser(BrowserAutomation):
    """BrowserAutomation hooks for RevoUninstaller authentication."""

    SESSION_NAME = "revo-uninstaller"
    LOGIN_URL = "https://www.revouninstaller.com/partners/"
    AUTH_CHECK_URL = "https://www.revouninstaller.com/partners/"
    AUTH_URL_PATTERN = r"/login"
