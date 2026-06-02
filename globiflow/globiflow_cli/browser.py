"""Browser automation service for Globiflow CLI."""

from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError


class AuthenticationRequired(Exception):
    """Raised when authentication is required but session is invalid."""


class BrowserError(BrowserAutomationError):
    """Browser automation error with context."""


class GlobiflowBrowser(BrowserAutomation):
    """Globiflow browser automation backed by cli_tools_shared BrowserAutomation."""

    SESSION_NAME = "globiflow"
    LOGIN_URL = "https://workflow-automation.podio.com"
    AUTH_CHECK_URL = "https://workflow-automation.podio.com/flows.php"
    AUTH_URL_PATTERN = r"/login|podio\.com/login|accounts\.podio\.com"
    AUTH_FAILURE_URL_PATTERN = r"^https://workflow-automation\.podio\.com/?(?:[?#].*)?$"


BrowserError = BrowserAutomationError
BrowserService = GlobiflowBrowser
