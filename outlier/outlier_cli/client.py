"""Outlier client using BrowserAutomation from cli_tools_shared.

app.outlier.ai is a Next.js SPA whose worker-facing screens read exclusively
from a JSON API under `/internal`, authorized by the `_jwt` session cookie
plus an `X-CSRF-Token` header the frontend copies out of the `_csrf` cookie.
Rather than scrape the rendered DOM, this client reproduces that same call
from inside the authenticated page — same URL, same header the site's own
`fetch` wrapper sends.

Verified live 2026-09-02 against Adam's authenticated session:
  - Without `X-CSRF-Token` every `/internal/*` call returns HTTP 401
    `{"status_code":401,"error":"Request does not have user"}`; with it the
    same call returns 200.
  - GET /internal/v2/tasks/peek_queue -> {"assignments":[...],
    "emptyQueueEvent":{...}, "isEmptyQueue":bool, "missionsCreated":bool}
  - GET /internal/logged_in_user -> the worker record.
"""

from typing import Any, Dict, List, Optional

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .browser import OutlierBrowser
from .config import get_config
from .parsers import (
    normalize_identity_verification,
    normalize_onboarding_status,
    normalize_onboarding_steps,
    normalize_profile,
    normalize_queue_status,
    normalize_task_detail,
    normalize_task_rows,
)

PEEK_QUEUE_PATH = "/internal/v2/tasks/peek_queue"
LOGGED_IN_USER_PATH = "/internal/logged_in_user"
ONBOARDING_PATH = "/internal/experts/qualification/onboarding/v2"
WORKER_PII_PATH = "/internal/worker/get_pii"
IDENTITY_ASSIGNMENTS_PATH = "/internal/identity-verification/assignments"
IDV_AUDIT_STATUS_PATH = "/internal/tns-audits/idv_audit_status"

# Runs inside the authenticated page so it can read the CSRF cookie the site
# itself reads and send the request exactly the way the site does.
FETCH_JS = """
async (path) => {
  const csrf = decodeURIComponent(
    (document.cookie.match(/(?:^|; )_csrf=([^;]*)/) || [])[1] || ''
  );
  const res = await fetch(path, {
    method: 'GET',
    credentials: 'include',
    headers: { 'Accept': 'application/json', 'X-CSRF-Token': csrf },
  });
  const text = await res.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch (e) { body = text; }
  return { status: res.status, ok: res.ok, body };
}
"""


class OutlierClient:
    """Client that uses BrowserAutomation to drive Outlier."""

    def __init__(self, profile: Optional[str] = None):
        self.config = get_config(profile)
        self._browser: Optional[OutlierBrowser] = None

    def _get_browser(self) -> OutlierBrowser:
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def close(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    def _fetch(self, path: str) -> Any:
        """GET one `/internal` path from inside the authenticated page."""
        browser = self._get_browser()
        try:
            page = browser.get_page(self.config.base_url)
            page.wait_for_timeout(1000)
            result = page.evaluate(FETCH_JS, path)
        finally:
            browser.close()
            self._browser = None
        if not isinstance(result, dict):
            raise ClientError(
                f"Unexpected response evaluating fetch for {path}: {result!r}"
            )
        if not result.get("ok"):
            raise ClientError(
                f"Outlier API request to {path} failed "
                f"(HTTP {result.get('status')}): {result.get('body')}"
            )
        return result.get("body")

    def _peek_queue(self) -> Dict[str, Any]:
        body = self._fetch(PEEK_QUEUE_PATH)
        if not isinstance(body, dict):
            raise ClientError(
                f"{PEEK_QUEUE_PATH} returned {type(body).__name__}, expected an object."
            )
        return body

    @cached
    def list_tasks(self, limit: int = 100) -> List[dict]:
        """Queued work assignments from Outlier's task queue."""
        rows = normalize_task_rows(self._peek_queue().get("assignments"))
        return rows[:limit]

    def get_task(self, task_id: str) -> dict:
        """Full detail for one queued assignment, by its `id` (the project id).

        Outlier exposes no per-assignment endpoint — the queue itself is the
        only representation of an assignment — so this reads the same queue
        and returns the matching entry in full.
        """
        assignments = self._peek_queue().get("assignments") or []
        for raw in assignments:
            if raw.get("projectId") == task_id:
                return normalize_task_detail(raw)
        raise ClientError(
            f"No queued Outlier task with id {task_id!r}. "
            f"The queue currently holds {len(assignments)} assignment(s)."
        )

    @cached
    def get_queue_status(self) -> dict:
        """Why the queue holds what it holds (empty-queue reasons included)."""
        return normalize_queue_status(self._peek_queue())


    def _onboarding(self) -> Dict[str, Any]:
        """Raw onboarding state. Never cached: it is what actions are judged by."""
        body = self._fetch(ONBOARDING_PATH)
        if not isinstance(body, dict):
            raise ClientError(
                f"{ONBOARDING_PATH} returned {type(body).__name__}, expected an object."
            )
        return body

    def get_onboarding_status(self) -> dict:
        """Current onboarding step, its status, and every step's state."""
        return normalize_onboarding_status(self._onboarding())

    def list_onboarding_steps(self, limit: int = 100) -> List[dict]:
        """The onboarding step list, one row per step."""
        return normalize_onboarding_steps(self._onboarding().get("qualifications"))[:limit]

    def get_onboarding_step(self, step_id: str) -> dict:
        """One onboarding step by its `id`."""
        steps = normalize_onboarding_steps(self._onboarding().get("qualifications"))
        for step in steps:
            if step["id"] == step_id:
                return step
        raise ClientError(
            f"No onboarding step with id {step_id!r}. Outlier lists: "
            f"{', '.join(str(s['id']) for s in steps)}."
        )

    def get_profile(self) -> dict:
        """The worker profile the Create Profile form is prefilled from."""
        body = self._fetch(WORKER_PII_PATH)
        if not isinstance(body, dict):
            raise ClientError(
                f"{WORKER_PII_PATH} returned {type(body).__name__}, expected an object."
            )
        return normalize_profile(body)

    def get_identity_verification(self) -> dict:
        """Identity-verification state behind the Persona / Verify identity step.

        Read-only. This CLI never starts, consents to, or completes an identity
        inquiry — that step needs a government ID and a selfie.
        """
        assignments = self._fetch(IDENTITY_ASSIGNMENTS_PATH)
        if not isinstance(assignments, dict):
            raise ClientError(
                f"{IDENTITY_ASSIGNMENTS_PATH} returned "
                f"{type(assignments).__name__}, expected an object."
            )
        return normalize_identity_verification(
            assignments, self._fetch(IDV_AUDIT_STATUS_PATH)
        )

    def verify_phone(
        self,
        phone: str,
        *,
        channel: str = "sms",
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> dict:
        """Complete the Create Profile step, including phone verification."""
        from .onboarding import verify_phone

        return verify_phone(
            self.config,
            phone,
            channel=channel,
            first_name=first_name,
            last_name=last_name,
        )

    def upload_resume(self, file_path: str) -> dict:
        """Attach a resume to the Import skills onboarding step."""
        from .onboarding import upload_resume

        return upload_resume(self.config, file_path)

    def get_logged_in_user(self) -> dict:
        """The authenticated worker record from /internal/logged_in_user."""
        body = self._fetch(LOGGED_IN_USER_PATH)
        if not isinstance(body, dict):
            raise ClientError(
                f"{LOGGED_IN_USER_PATH} returned {type(body).__name__}, "
                "expected an object."
            )
        return body


_clients: dict = {}


def get_client(profile: Optional[str] = None) -> OutlierClient:
    """Get or create the Outlier client instance for a profile."""
    key = profile or "_default"
    if key not in _clients:
        _clients[key] = OutlierClient(profile=profile)
    return _clients[key]
