"""Browser automation service for Raptive CLI.

Subclasses BrowserAutomation from cli_tools_shared for CDP-based login,
session persistence, and headless automation.
"""
from cli_tools_shared.auth import BrowserAutomation


class RaptiveBrowser(BrowserAutomation):
    """Raptive-specific browser automation."""

    LOGIN_URL = "https://dashboard.raptive.com"
    AUTH_CHECK_URL = "https://dashboard.raptive.com"
    AUTH_URL_PATTERN = r"/login|accounts\.google\.com"
    AUTH_SUCCESS_URL = r"/sites/"
    AUTH_STORAGE_KEY = "token"
    AUTH_STORAGE_KEY_IS_JWT = True
    SESSION_NAME = "raptive"
