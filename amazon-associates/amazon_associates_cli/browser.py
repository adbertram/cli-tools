"""Browser session automation for AmazonAssociates."""
from cli_tools_shared.auth import BrowserAutomation


class AmazonAssociatesBrowser(BrowserAutomation):
    """BrowserAutomation hooks for AmazonAssociates authentication."""

    SESSION_NAME = "amazon-associates"
    LOGIN_URL = "https://affiliate-program.amazon.com/"
    AUTH_CHECK_URL = "https://affiliate-program.amazon.com/"
    AUTH_URL_PATTERN = r"/login"
