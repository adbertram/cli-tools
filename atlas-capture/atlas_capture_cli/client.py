"""Atlas Capture client using BrowserAutomation from cli_tools_shared.

Atlas Capture's worker portal is a Next.js app whose data is fetched as JSON
from internal tRPC endpoints and never server-rendered, so this client
reproduces the site's own calls from inside the authenticated page instead of
scraping the DOM. Authorization rides on the session cookies Atlas sets at
login (``stytch_session_token``, ``mecka_device_key``) — a same-origin fetch
with ``credentials: 'include'`` is authorized exactly like the site's own.

Confirmed live 2026-09-03 against Adam's authenticated session (see parsers.py
for field-level notes and the reason ``tasks`` is currently empty):
  - GET /api/trpc/user.me
  - GET /api/trpc/rooms.getConfig
  - GET /api/trpc/user.getAccountStatus
  - GET /api/trpc/payment.getSurgeStatus
  - GET /api/trpc/humanVerifier.migrationExperience
  - GET /api/trpc/certification.getAll

``list_tasks`` asks the site for /tasks; the route currently redirects to
/dashboard for this account (no task surface: not certified, and the platform
is under a "Temporary Labeling Pause"), which yields an honest empty list.
"""

from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import print_info

from . import parsers
from .browser import AtlasCaptureBrowser
from .config import get_config

# Runs inside the authenticated page. Atlas keeps no token in localStorage —
# the session cookies authorize the call, so this sends the same same-origin
# GET the site's own tRPC client sends.
FETCH_JS = """
async ([path]) => {
  const res = await fetch(path, {
    method: 'GET',
    credentials: 'include',
    headers: { 'Accept': 'application/json', 'Content-Type': 'application/json' },
  });
  const text = await res.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch (e) { body = text; }
  return { status: res.status, ok: res.ok, body };
}
"""

URL_JS = "() => location.href"
BODY_TEXT_JS = "() => (document.body ? document.body.innerText : '')"


class AtlasCaptureClient:
    """Client that uses BrowserAutomation to drive Atlas Capture."""

    def __init__(self):
        self.config = get_config()
        self._browser: Optional[AtlasCaptureBrowser] = None

    def _get_browser(self) -> AtlasCaptureBrowser:
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def close(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    @contextmanager
    def _page(self, url: str = parsers.DASHBOARD_URL):
        """Open the given same-origin page on a fresh browser session.

        Any authenticated page works — the session cookies authorize the
        fetch. The browser is closed on exit.
        """
        browser = self._get_browser()
        try:
            page = browser.get_page(url)
            page.wait_for_timeout(1500)
            yield page
        finally:
            browser.close()

    def _fetch_trpc(self, page, procedure: str) -> Any:
        """GET one tRPC procedure from inside the page and unwrap its payload."""
        result = page.evaluate(FETCH_JS, [f"/api/trpc/{procedure}"])
        if not isinstance(result, dict):
            raise ClientError(
                f"Unexpected response evaluating fetch for {procedure}: {result!r}"
            )
        if not result.get("ok"):
            detail = str(result.get("body"))[:300]
            raise ClientError(
                f"Atlas Capture API request to {procedure} failed "
                f"(HTTP {result.get('status')}): {detail}"
            )
        body = result.get("body")
        if isinstance(body, str):
            raise ClientError(
                f"Atlas Capture API request to {procedure} returned a "
                f"non-JSON body: {body[:200]}"
            )
        return parsers.unwrap_trpc(body)

    def list_tasks(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List the tasks Atlas exposes to this account right now.

        The ground truth is where the site itself sends an authenticated
        request for /tasks: today it redirects to /dashboard for this account
        (no task surface), which returns an empty list after a stderr note.
        The day the route stays on /tasks with an empty queue this also
        returns []; if the queue visibly holds rows, a real task record must
        be captured before any row can be parsed (no schema is guessed).
        """
        with self._page(parsers.TASKS_URL) as page:
            page.wait_for_timeout(2000)
            final_url = self._settled_url(page)
            page_text = (page.evaluate(BODY_TEXT_JS) or "").strip()
            page_text = " ".join(page_text.split())[:4000]

        state = parsers.evaluate_tasks_route_state(final_url, page_text)
        if not state["has_tasks_surface"]:
            print_info(f"Atlas Capture: {state['reason']}")
            return []
        if state.get("empty"):
            print_info("Atlas Capture: the task queue is currently empty.")
            return []
        # On /tasks with content we do not recognise: never guess a schema.
        raise ClientError(
            "Atlas Capture shows a task surface with content, but no real "
            "Atlas task record has been captured yet, so the rows cannot be "
            "parsed. Capture the page state (and its tRPC payloads) first "
            "and implement the mapping from that real record."
        )

    def get_task(self, task_id: str) -> Dict[str, Any]:
        """Get one task. Unavailable while the account has no task surface."""
        raise ClientError(
            "Atlas Capture exposes no tasks to this account right now (the "
            "/tasks route redirects to /dashboard: not certified and/or "
            "labeling paused), so no task detail can be fetched. "
            f"No task with id {task_id!r} exists to return."
        )

    def account(self) -> Dict[str, Any]:
        """Normalized user.me record (live account facts for this session)."""
        with self._page(parsers.DASHBOARD_URL) as page:
            payload = self._fetch_trpc(page, "user.me")
        if not isinstance(payload, dict):
            raise ClientError(f"user.me returned a non-object payload: {payload!r}")
        return parsers.normalize_user_me(payload)

    def _settled_url(self, page) -> str:
        """Current URL once redirects settle (up to ~8s)."""
        for _ in range(8):
            url = (page.evaluate(URL_JS) or "").strip()
            if any(marker in url for marker in ("/login", "/verify", "/dashboard",
                                                "/tasks")):
                return url
            page.wait_for_timeout(1000)
        return (page.evaluate(URL_JS) or "").strip()


_client: Optional[AtlasCaptureClient] = None


def get_client() -> AtlasCaptureClient:
    """Get or create the global Atlas Capture client instance."""
    global _client
    if _client is None:
        _client = AtlasCaptureClient()
    return _client
