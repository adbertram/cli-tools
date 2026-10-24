"""CrowdGen (Appen) client using BrowserAutomation from cli_tools_shared.

CrowdGen's worker frontend reads and writes exclusively through a JSON API at
https://api.crowdgen.com/api/v1/ (endpoints and auth model extracted from the
deployed bundle main.b5c37aa5.js, 2026-09-03: the SPA keeps an auth cookie
"authToken"/"authjwt" and sends `Authorization: Bearer <token>`; axios also
defaults `Authorization: Bearer <token>` from the cookie). This client
reproduces that same fetch from inside the authenticated app.crowdgen.com page
so cookies/CORS behave exactly as the site's own code does.

Worker-surface endpoints named by the bundle:
  - GET .../api/v1/projects/available   (project matchmaking "available")
  - GET .../api/v1/projects/active
  - GET .../api/v1/projects/match
  - GET .../api/v1/adap/contributorProjects  (ADAP contributor projects)

Live record shapes are NOT yet mapped: no authenticated capture exists
(registration is Kasada-blocked for automation and remaining sign-up steps are
human gates). `tasks list` therefore returns [] for provably-empty dashboards
(pre-shortlist state) and raises a clear unverified-shape error otherwise —
see parsers.py. Nothing here invents record fields.
"""

from contextlib import contextmanager
from typing import List, Optional

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .browser import CrowdgenBrowser
from .config import get_config
from .parsers import task_rows

# Runs inside the authenticated page so it can send the site's own
# Authorization header (from the auth cookie) plus the session cookies.
FETCH_JS = """
async (url) => {
  const readCookie = (name) => {
    const m = document.cookie.match(new RegExp('(^|;\\\\s*)' + name + '=([^;]*)'));
    return m ? decodeURIComponent(m[2]) : null;
  };
  const token = readCookie('authToken') || readCookie('authjwt');
  const headers = { 'Accept': 'application/json' };
  if (token) headers['Authorization'] = 'Bearer ' + token;
  const res = await fetch(url, { method: 'GET', credentials: 'include', headers });
  const text = await res.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch (e) { body = text; }
  return { status: res.status, ok: res.ok, body };
}
"""


class CrowdgenClient:
    """Client that uses BrowserAutomation to drive CrowdGen."""

    def __init__(self):
        self.config = get_config()
        self._browser: Optional[CrowdgenBrowser] = None

    def _get_browser(self) -> CrowdgenBrowser:
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def close(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    def _require_authenticated(self) -> None:
        browser = self._get_browser()
        try:
            if not browser.is_authenticated():
                raise ClientError(
                    "CrowdGen session needed. Run 'crowdgen auth login' — a "
                    "session exists only after the account completed CrowdGen "
                    "onboarding."
                )
        finally:
            browser.close()

    def _api_url(self, path: str) -> str:
        base = getattr(self.config, "API_BASE_URL", "https://api.crowdgen.com")
        return f"{base.rstrip('/')}/api/v1/{path.lstrip('/')}"

    @contextmanager
    def _authenticated_page(self):
        """Open an authenticated page on a fresh browser, closing it on exit."""
        browser = self._get_browser()
        try:
            page = browser.get_page("https://app.crowdgen.com/")
            page.wait_for_timeout(1000)
            yield page
        finally:
            browser.close()

    def _fetch(self, page, endpoint: str) -> dict:
        url = self._api_url(endpoint)
        result = page.evaluate(FETCH_JS, url)
        if not isinstance(result, dict):
            raise ClientError(
                f"Unexpected response evaluating CrowdGen fetch for {endpoint}: {result!r}"
            )
        if result.get("status") == 401:
            raise ClientError(
                "CrowdGen API returned 401 (session expired). Run 'crowdgen auth login --force'."
            )
        if not result.get("ok"):
            raise ClientError(
                f"CrowdGen API request to {endpoint} failed "
                f"(HTTP {result.get('status')}): {str(result.get('body'))[:200]}"
            )
        return result.get("body")

    @cached
    def list_tasks(self, limit: int = 100) -> List[dict]:
        """List available CrowdGen projects/tasks from projects/available."""
        endpoint = "projects/available"
        self._require_authenticated()
        with self._authenticated_page() as page:
            body = self._fetch(page, endpoint)
        rows = task_rows(endpoint, body)
        return rows[:limit] if limit else rows

    def get_task(self, task_id: str) -> dict:
        """Get full detail for a single task by its id.

        CrowdGen lists projects rather than individual micro-tasks; a record
        for `task_id` can only come from the same available-projects listing.
        No per-task detail endpoint is documented/observed yet.
        """
        rows = self.list_tasks(limit=0)
        for row in rows:
            if str(row.get("id")) == str(task_id):
                return row
        raise ClientError(
            f"CrowdGen task {task_id!r} not found in projects/available "
            "(dashboard may be empty until shortlisted)."
        )


_client: Optional[CrowdgenClient] = None


def get_client() -> CrowdgenClient:
    """Get or create the global Crowdgen client instance."""
    global _client
    if _client is None:
        _client = CrowdgenClient()
    return _client
