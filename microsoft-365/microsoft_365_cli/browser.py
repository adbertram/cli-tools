"""Browser session automation for Microsoft365."""
from cli_tools_shared.auth import BrowserAutomation


class Microsoft365Browser(BrowserAutomation):
    """BrowserAutomation hooks for Microsoft365 authentication."""

    SESSION_NAME = "microsoft-365"
    LOGIN_URL = "https://www.microsoft.com/en-us/microsoft-365/business/microsoft-365-affiliate-program?ms.officeurl=affiliate"
    AUTH_CHECK_URL = "https://www.microsoft.com/en-us/microsoft-365/business/microsoft-365-affiliate-program?ms.officeurl=affiliate"
    AUTH_URL_PATTERN = r"/login"
