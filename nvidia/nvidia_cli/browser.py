"""Browser session automation for Nvidia."""
from cli_tools_shared.auth import BrowserAutomation


class NvidiaBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Nvidia authentication."""

    SESSION_NAME = "nvidia"
    LOGIN_URL = "https://www.nvidia.com/en-us/affiliates/"
    AUTH_CHECK_URL = "https://www.nvidia.com/en-us/affiliates/"
    AUTH_URL_PATTERN = r"/login"
