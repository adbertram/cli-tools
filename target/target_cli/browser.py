"""Declarative browser hooks for Target.

Auth lifecycle lives in ``cli_tools_shared`` (account login) and in ``prime.py``
(the redsky read-session capture). This class only declares the shared hook
constants -- no methods.
"""

from cli_tools_shared.auth import BrowserAutomation


class TargetBrowser(BrowserAutomation):
    """Declarative browser automation hooks for Target."""

    SESSION_NAME = "target"
    LOGIN_URL = "https://www.target.com/login"
    AUTH_CHECK_URL = "https://www.target.com/account"
    AUTH_URL_PATTERN = r"/login|/signin|/register"
    AUTH_COOKIE_PATTERNS = ["accessToken", "idToken", "login-session"]
    AUTH_SUCCESS_SELECTOR = 'button[data-test="@web/AccountLink"], [data-test="@web/AccountMenu"]'
    AUTH_LOGIN_FORM_SELECTOR = 'input[type="password"]'
    MANUAL_LOGIN = True
