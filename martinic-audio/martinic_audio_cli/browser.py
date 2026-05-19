"""Browser session automation for MartinicAudio."""
from cli_tools_shared.auth import BrowserAutomation


class MartinicAudioBrowser(BrowserAutomation):
    """BrowserAutomation hooks for MartinicAudio authentication."""

    SESSION_NAME = "martinic-audio"
    LOGIN_URL = "https://www.martinic.com/en/products"
    AUTH_CHECK_URL = "https://www.martinic.com/en/products"
    AUTH_URL_PATTERN = r"/login"
