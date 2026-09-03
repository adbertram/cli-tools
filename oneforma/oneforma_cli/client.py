"""OneForma client using BrowserAutomation from cli_tools_shared.

OneForma's contributor site is a React SPA whose job data is fetched as JSON
from an internal API and never server-rendered, so this client reproduces the
site's own calls from inside the authenticated page instead of scraping the
DOM. Authorization rides on the session cookies OneForma sets at login
(`accessToken`, `of-refresh-token`, `JSESSIONID`) — a same-origin fetch with
`credentials: 'include'` is authorized exactly like the site's own XHRs.

Endpoints confirmed live 2026-09-02 against an authenticated session (see
parsers.py for the field-level notes):
  - POST /api/resource/job/v1/list-job   {"page": 1, "size": <int>}
  - POST /api/resource/job/v1/get-detail {"jobId": "<id>"}
"""

from contextlib import contextmanager
from typing import List, Optional

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .browser import DASHBOARD_URL, OneformaBrowser
from .config import get_config
from .parsers import normalize_job_detail, normalize_job_rows

# Runs inside the authenticated page. OneForma keeps no token in
# localStorage — the session cookies authorize the call, so this sends the
# same same-origin POST the site's own code sends.
FETCH_JS = """
async ([path, payload]) => {
  const res = await fetch(path, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json, text/plain, */*',
    },
    body: JSON.stringify(payload),
  });
  const text = await res.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch (e) { body = text; }
  return { status: res.status, ok: res.ok, body };
}
"""

LIST_JOB_PATH = "/api/resource/job/v1/list-job"
GET_DETAIL_PATH = "/api/resource/job/v1/get-detail"


class OneformaClient:
    """Client that uses BrowserAutomation to drive OneForma."""

    def __init__(self):
        self.config = get_config()
        self._browser: Optional[OneformaBrowser] = None

    def _get_browser(self) -> OneformaBrowser:
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def close(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    @contextmanager
    def _page(self):
        """Open the contributor dashboard (any authenticated same-origin page
        works — the session cookies authorize the fetch) on a fresh browser
        session, closing it on exit."""
        browser = self._get_browser()
        try:
            page = browser.get_page(DASHBOARD_URL)
            page.wait_for_timeout(1000)
            yield page
        finally:
            browser.close()

    def _post(self, page, path: str, payload: dict) -> dict:
        result = page.evaluate(FETCH_JS, [path, payload])
        if not isinstance(result, dict):
            raise ClientError(
                f"Unexpected response evaluating fetch for {path}: {result!r}"
            )
        if not result.get("ok"):
            raise ClientError(
                f"OneForma API request to {path} failed "
                f"(HTTP {result.get('status')}): {result.get('body')}"
            )
        body = result.get("body")
        if not isinstance(body, dict):
            raise ClientError(
                f"OneForma API request to {path} returned a non-JSON body: {body!r}"
            )
        # OneForma answers HTTP 200 with success=false for application-level
        # errors, so the envelope has to be checked, not just the status.
        if not body.get("success"):
            raise ClientError(
                f"OneForma API request to {path} was rejected "
                f"(code {body.get('code')}): {body.get('message')} {body.get('data')}"
            )
        data = body.get("data")
        if not isinstance(data, dict):
            raise ClientError(
                f"OneForma API request to {path} returned no data object: {body!r}"
            )
        return data

    @cached
    def list_tasks(self, limit: int = 100) -> List[dict]:
        """List open jobs from /api/resource/job/v1/list-job."""
        with self._page() as page:
            data = self._post(page, LIST_JOB_PATH, {"page": 1, "size": limit})
        rows = normalize_job_rows(data.get("records"))
        return rows[:limit]

    def get_task(self, task_id: str) -> dict:
        """Fetch full detail for one job by its jobId."""
        with self._page() as page:
            data = self._post(page, GET_DETAIL_PATH, {"jobId": str(task_id)})
        return normalize_job_detail(data, str(task_id))


_client: Optional[OneformaClient] = None


def get_client() -> OneformaClient:
    """Get or create the global OneForma client instance."""
    global _client
    if _client is None:
        _client = OneformaClient()
    return _client
