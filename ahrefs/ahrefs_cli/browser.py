"""Browser automation service for Ahrefs CLI.

Subclasses BrowserAutomation from cli_tools_shared for CDP-based login,
session persistence, and headless automation.
"""
import json
from typing import Any, Callable, Dict, List

from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError
from cli_tools_shared.http_session import BrowserAuthenticatedHttpClient, BrowserAuthState


class AhrefsBrowser(BrowserAutomation):
    """Ahrefs-specific browser automation."""

    LOGIN_URL = "https://app.ahrefs.com"
    AUTH_CHECK_URL = "https://app.ahrefs.com"
    AUTH_URL_PATTERN = r"/login|/user/login"
    AUTH_SUCCESS_URL = r"/dashboard"
    AUTH_COOKIE_PATTERNS = [r"^BSSESSID$"]
    AUTH_COOKIE_DOMAINS = ("ahrefs.com", "app.ahrefs.com")
    AUTH_SUCCESS_SELECTOR = ".user-menu, [data-testid='user-menu']"
    SESSION_NAME = "ahrefs"
    AUTOMATION_HEADED = True

    def fetch_json(self, url: str) -> Any:
        """Fetch JSON using the shared saved browser auth state."""
        client = BrowserAuthenticatedHttpClient(
            BrowserAuthState.from_config(self.config),
            allowed_domains=("ahrefs.com",),
            headers={"Accept": "application/json"},
        )
        return json.loads(client.get_text(url))

    def extract_table(self, table: str = "table", headers: str = "thead th",
                      rows: str = "tbody tr", cells: str = "td") -> List[Dict]:
        """Extract data from HTML table as list of dicts."""
        page = self.get_page()
        t = page.locator(table)
        hdrs = [h.strip() for h in t.locator(headers).all_text_contents()]
        return [
            {hdrs[i]: c for i, c in enumerate(r.locator(cells).all_text_contents()[:len(hdrs)])}
            if hdrs else {f"col_{i}": c for i, c in enumerate(r.locator(cells).all_text_contents())}
            for r in t.locator(rows).all()
        ]

    def paginate(self, next_sel: str, extract: Callable, max_pages: int = 10) -> List:
        """Extract data across multiple pages."""
        page = self.get_page()
        data = []
        for _ in range(max_pages):
            data.extend(extract())
            btn = page.locator(next_sel)
            if btn.count() == 0 or not btn.is_enabled():
                break
            btn.click()
            page.wait_for_timeout(2000)
        return data


# Backward compatibility aliases
BrowserService = AhrefsBrowser
BrowserError = BrowserAutomationError
