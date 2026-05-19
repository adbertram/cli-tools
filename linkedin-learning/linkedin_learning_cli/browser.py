"""Browser session automation for LinkedinLearning."""
from cli_tools_shared.auth import BrowserAutomation


class LinkedinLearningBrowser(BrowserAutomation):
    """BrowserAutomation hooks for LinkedinLearning authentication."""

    SESSION_NAME = "linkedin-learning"
    LOGIN_URL = "https://learning.linkedin.com/affiliate-program"
    AUTH_CHECK_URL = "https://learning.linkedin.com/affiliate-program"
    AUTH_URL_PATTERN = r"/login"
