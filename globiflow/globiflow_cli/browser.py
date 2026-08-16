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

    # Non-interactive login: LOGIN_URL redirects through podio.com/oauth/authorize
    # to podio.com/login, a plain Email/Password/Sign-In form (verified via a
    # read-only DOM probe on 2026-08-14 -- stable ids, no framework churn).
    AUTH_LOGIN_USERNAME_SELECTOR = "#email"
    AUTH_LOGIN_PASSWORD_SELECTOR = "#password"
    AUTH_LOGIN_SUBMIT_SELECTOR = "#loginFormSignInButton"
    AUTH_LOGIN_USERNAME_SECRET = "globiflow-username"
    AUTH_LOGIN_PASSWORD_SECRET = "globiflow-password"


BrowserError = BrowserAutomationError
BrowserService = GlobiflowBrowser
