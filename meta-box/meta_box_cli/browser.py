"""Browser session automation for MetaBox."""
from cli_tools_shared.auth import BrowserAutomation


class MetaBoxBrowser(BrowserAutomation):
    """BrowserAutomation hooks for MetaBox authentication."""

    SESSION_NAME = "meta-box"
    LOGIN_URL = "https://metabox.io/"
    AUTH_CHECK_URL = "https://metabox.io/"
    AUTH_URL_PATTERN = r"/login"
