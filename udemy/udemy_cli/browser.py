"""Browser-backed Udemy helpers."""
from __future__ import annotations

from cli_tools_shared.auth import BrowserAutomation


UDEMY_BROWSER_SESSION = "udemy"
UDEMY_ORIGIN = "https://www.udemy.com"


class UdemyBrowser(BrowserAutomation):
    """Browser authentication for Udemy instructor pages."""

    LOGIN_URL = "https://www.udemy.com/join/login-popup/"
    AUTH_CHECK_URL = "https://www.udemy.com/instructor/courses/"
    AUTH_URL_PATTERN = r"/join/login|/user/login|/login"
    AUTH_COOKIE_PATTERNS = [r"^(access_token|ud_user_jwt|dj_session_id)$"]
    AUTH_COOKIE_DOMAINS = ("udemy.com",)
    AUTH_SUCCESS_SELECTOR = "a[href='/instructor/courses']"
    SESSION_NAME = UDEMY_BROWSER_SESSION
    AUTOMATION_HEADED = True


def _udemy_session_name(self) -> str:
    return self.config.browser_session


UdemyBrowser._session_name = _udemy_session_name
