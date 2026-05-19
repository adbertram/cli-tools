"""Browser automation for Progress ServiceNow."""

from cli_tools_shared.auth import BrowserAutomation
from cli_tools_shared.http_session import BrowserAuthState


class ProgressServiceNowBrowser(BrowserAutomation):
    SESSION_NAME = "progress-servicenow"
    LOGIN_URL = "https://progress1.service-now.com/esc"
    AUTH_CHECK_URL = "https://progress1.service-now.com/esc"
    AUTH_URL_PATTERN = r"login\.microsoftonline\.com"
    AUTH_COOKIE_PATTERNS = [r"^glide_session_store$"]

    def auth_state(self) -> BrowserAuthState:
        return BrowserAuthState.from_config(self.config)

    def open_headed(self, url: str):
        svc = self._get_service()
        svc.browser_open(
            url=url,
            persistent=True,
            headed=True,
        )
        self._page = svc
        return svc
