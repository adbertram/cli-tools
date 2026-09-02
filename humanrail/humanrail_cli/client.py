"""HumanRail client using BrowserAutomation from cli_tools_shared.

HumanRail (routehuman.com) is a React SPA whose worker-facing UI reads and
writes exclusively through a JSON API under `/api`, authorized by a bearer
token the frontend keeps in localStorage (`ee_auth_token` — see
`browser.py`). Rather than scrape the rendered DOM, this client reproduces
that same fetch from inside the authenticated page (same URL, same
`Authorization: Bearer <token>` header the site's own code sends), which is
both simpler and more robust than a DOM scraper for a JSON-backed SPA.

Endpoints below were confirmed live 2026-09-02 against an authenticated
session:
  - GET /api/workers/me/tasks/available -> {"tasks": [...], "total": <int>}
  - GET /api/workers/me/tasks/<id>      -> a single task object
"""

from contextlib import contextmanager
from typing import List, Optional

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .browser import HumanrailBrowser
from .config import get_config
from .parsers import normalize_task_detail, normalize_task_rows

# Runs inside the authenticated page so it can read the bearer token the
# site itself stores in localStorage and send it exactly like the site does.
FETCH_JS = """
async (path) => {
  const token = localStorage.getItem('ee_auth_token');
  const res = await fetch(path, {
    method: 'GET',
    headers: {
      'Authorization': token ? `Bearer ${token}` : '',
      'Accept': 'application/json',
    },
  });
  const text = await res.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch (e) { body = text; }
  return { status: res.status, ok: res.ok, body };
}
"""

MAX_LIST_PAGES = 25  # matches the worker-job list cap used by sibling CLIs


class HumanrailClient:
    """Client that uses BrowserAutomation to drive HumanRail."""

    def __init__(self):
        self.config = get_config()
        self._browser: Optional[HumanrailBrowser] = None

    def _get_browser(self) -> HumanrailBrowser:
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def close(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    @contextmanager
    def _page(self):
        """Open the dashboard (any authenticated page works — the token
        lives in localStorage, not per-page state) on a fresh browser
        session, closing it on exit."""
        browser = self._get_browser()
        try:
            page = browser.get_page("https://routehuman.com/dashboard")
            page.wait_for_timeout(1000)
            yield page
        finally:
            browser.close()

    def _fetch(self, page, path: str) -> dict:
        result = page.evaluate(FETCH_JS, path)
        if not isinstance(result, dict):
            raise ClientError(f"Unexpected response evaluating fetch for {path}: {result!r}")
        if not result.get("ok"):
            raise ClientError(
                f"HumanRail API request to {path} failed "
                f"(HTTP {result.get('status')}): {result.get('body')}"
            )
        return result.get("body") or {}

    @cached
    def list_tasks(self, limit: int = 100) -> List[dict]:
        """List available worker tasks from /api/workers/me/tasks/available."""
        with self._page() as page:
            body = self._fetch(page, "/api/workers/me/tasks/available")
        rows = normalize_task_rows(body.get("tasks"))
        return rows[:limit]

    def get_task(self, task_id: str) -> dict:
        """Fetch full detail for one task by its id."""
        with self._page() as page:
            body = self._fetch(page, f"/api/workers/me/tasks/{task_id}")
        return normalize_task_detail(body)


_client: Optional[HumanrailClient] = None


def get_client() -> HumanrailClient:
    """Get or create the global HumanRail client instance."""
    global _client
    if _client is None:
        _client = HumanrailClient()
    return _client
