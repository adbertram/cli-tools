"""Browser automation service for Globiflow CLI."""

import json
from typing import Any, Callable, Dict, List

from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError
from cli_tools_shared.http_session import BrowserAuthenticatedHttpClient, BrowserAuthState
from cli_tools_shared.output import print_warning


class AuthenticationRequired(Exception):
    """Raised when authentication is required but session is invalid."""


class BrowserError(BrowserAutomationError):
    """Browser automation error with context."""


class GlobiflowBrowser(BrowserAutomation):
    """Globiflow browser automation backed by cli_tools_shared BrowserAutomation."""

    SESSION_NAME = "globiflow"
    LOGIN_URL = "https://workflow-automation.podio.com"
    AUTH_CHECK_URL = "https://workflow-automation.podio.com/flows.php"
    AUTH_URL_PATTERN = r"/login|podio\.com/login|accounts\.podio\.com"
    AUTH_COOKIE_PATTERNS = [r"session.*", r"auth", r"token", r"sid"]

    @property
    def page(self):
        return self.get_page()._get_page()

    def navigate(self, url: str):
        self.get_page(url)

    def wait(self, ms: int):
        self.page.wait_for_timeout(ms)

    def restore_session(self):
        """BrowserAutomation restores auth-state before first navigation."""

    def save_session(self):
        """Persist current auth-state without closing the browser."""
        if self._page is None:
            return
        state_file = self._get_browser_data_dir() / "auth-state.json"
        self._get_service().state_save(str(state_file))

    def logout(self):
        self.clear_session()

    def extract_table(
        self,
        table: str = "table",
        headers: str = "thead th",
        rows: str = "tbody tr",
        cells: str = "td",
    ) -> List[Dict]:
        t = self.page.locator(table)
        hdrs = [h.strip() for h in t.locator(headers).all_text_contents()]
        return [
            {hdrs[i]: c for i, c in enumerate(r.locator(cells).all_text_contents()[:len(hdrs)])}
            if hdrs else {f"col_{i}": c for i, c in enumerate(r.locator(cells).all_text_contents())}
            for r in t.locator(rows).all()
        ]

    def extract_list(self, selector: str, fields: Dict[str, str]) -> List[Dict]:
        items = []
        for element in self.page.locator(selector).all():
            row = {}
            for name, field_selector in fields.items():
                locator = element.locator(field_selector).first
                row[name] = locator.text_content().strip() if locator.count() else None
            items.append(row)
        return items

    def get_text(self, selector: str) -> str:
        locator = self.page.locator(selector).first
        return locator.text_content().strip() if locator.count() else ""

    def click_load_more(self, selector: str, max_clicks: int = 5):
        for _ in range(max_clicks):
            button = self.page.locator(selector).first
            if not button.count() or not button.is_enabled():
                return
            button.click()
            self.page.wait_for_timeout(1000)

    def paginate(self, next_sel: str, extract: Callable, max_pages: int = 10) -> List:
        data = []
        for _ in range(max_pages):
            data.extend(extract())
            btn = self.page.locator(next_sel)
            if btn.count() == 0 or not btn.is_enabled():
                break
            btn.click()
            self.page.wait_for_timeout(2000)
        return data

    def retry(self, action: Callable, attempts: int = 3, delay: int = 1000) -> Any:
        for i in range(attempts):
            try:
                return action()
            except Exception:
                if i == attempts - 1:
                    raise
                print_warning(f"Attempt {i + 1} failed, retrying...")
                self.page.wait_for_timeout(delay * (2 ** i))

    def fetch_json(self, url: str) -> Any:
        client = BrowserAuthenticatedHttpClient(
            BrowserAuthState.from_config(self.config),
            allowed_domains=("podio.com", "workflow-automation.podio.com"),
            headers={"Accept": "application/json"},
        )
        return json.loads(client.get_text(url))


BrowserError = BrowserAutomationError
BrowserService = GlobiflowBrowser
