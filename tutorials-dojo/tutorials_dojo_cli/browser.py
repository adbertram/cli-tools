"""Browser session automation for TutorialsDojo."""
from cli_tools_shared.auth import BrowserAutomation


class TutorialsDojoBrowser(BrowserAutomation):
    """BrowserAutomation hooks for TutorialsDojo authentication."""

    SESSION_NAME = "tutorials-dojo"
    LOGIN_URL = "https://portal.tutorialsdojo.com/faq-for-affiliate-marketing/"
    AUTH_CHECK_URL = "https://portal.tutorialsdojo.com/faq-for-affiliate-marketing/"
    AUTH_URL_PATTERN = r"/login"
