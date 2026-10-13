"""Declarative Vyro login through the shared persistent browser engine."""
from cli_tools_shared.auth import BrowserAutomation


class VyroBrowser(BrowserAutomation):
    LOGIN_URL = "https://app.vyro.com/login"
    AUTH_CHECK_URL = "https://app.vyro.com/campaigns"
    AUTH_URL_PATTERN = r"/login(?:/|\?|$)"
    AUTH_COOKIE_PATTERNS = ["vyro_rt"]
    SESSION_NAME = "vyro"
    MANUAL_LOGIN = True
