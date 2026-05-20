"""Browser session automation for Progress ServiceNow."""

from cli_tools_shared.auth import BrowserAutomation


class ProgressServiceNowBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Progress ServiceNow authentication."""

    SESSION_NAME = "progress-servicenow"
    LOGIN_URL = "https://progress1.service-now.com/esc"
    AUTH_CHECK_URL = "https://progress1.service-now.com/esc"
    AUTH_URL_PATTERN = r"login\.microsoftonline\.com"
    AUTH_COOKIE_PATTERNS = [r"^glide_session_store$"]
