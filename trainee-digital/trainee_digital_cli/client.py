"""TraineeDigital client using BrowserAutomation from cli_tools_shared.

trainee.digital's worker surface is a React SPA whose order feed comes from an
internal JSON API on the same origin. The site's own code authenticates those
calls with a short-lived Clerk session token minted from the ``__session``
cookie via the Clerk frontend API (``clerk.trainee.digital/v1/...``) and sent
as ``Authorization: Bearer <jwt>`` -- cookie-only requests get HTTP 401
(validated live 2026-09-03). Rather than scraping the rendered DOM, this
client reproduces that same mint-and-fetch from inside the authenticated page,
exactly like the mercor, outlier and oneforma CLIs do for their internal APIs.

Endpoints confirmed live 2026-09-03 against Adam's authenticated session (see
tests/fixtures/ for the exact payloads):
  - GET /api/orders              -> [ {id, title, category, pay, unit,
                                      volume, deadline, posted}, ... ]
  - GET /api/orders/<id>         -> one order, plus totalPay, dataset, scope,
                                    guidelines, createdAt
  - GET /api/me/profile          -> {"role": "candidate", ...} (the live auth
                                    round-trip used by `auth test`)
"""

from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .browser import TraineeDigitalBrowser
from .config import get_config
from .parsers import normalize_order_detail, normalize_orders

ORDERS_URL = "https://trainee.digital/orders"
PROFILE_PATH = "/api/me/profile"
ORDERS_PATH = "/api/orders"

# Runs inside the authenticated page on trainee.digital. Reproduces the site's
# own auth: mint a fresh session token from the Clerk frontend API (the
# ``__session`` cookie authorizes that call), then send it as Bearer -- the
# only form the /api/* backend accepts.
FETCH_JS = """
async ([path]) => {
  const clientRes = await fetch('https://clerk.trainee.digital/v1/client?__clerk_api_version=2026-05-12', {
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });
  const clientBody = await clientRes.json();
  const client = clientBody.response || clientBody;
  const session = (client.sessions || [])[0];
  let jwt = '';
  if (session && session.id) {
    const tokenRes = await fetch('https://clerk.trainee.digital/v1/client/sessions/' + session.id + '/tokens?__clerk_api_version=2026-05-12', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Accept': 'application/json', 'Content-Type': 'application/json' },
      body: '{}',
    });
    const tokenBody = await tokenRes.json();
    jwt = tokenBody.jwt || (tokenBody.response && tokenBody.response.jwt) || '';
  }
  const headers = { 'Accept': 'application/json, text/plain, */*' };
  if (jwt) headers.Authorization = 'Bearer ' + jwt;
  const res = await fetch(path, { method: 'GET', credentials: 'include', headers });
  const text = await res.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch (e) { body = text; }
  return { status: res.status, ok: res.ok, body };
}
"""


class TraineeDigitalClient:
    """Client that uses BrowserAutomation to drive TraineeDigital."""

    def __init__(self, profile: Optional[str] = None):
        self.config = get_config(profile)
        self._browser: Optional[TraineeDigitalBrowser] = None

    def _get_browser(self) -> TraineeDigitalBrowser:
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def close(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    @contextmanager
    def _page(self):
        """Open the orders page (any authenticated same-origin page works --
        the fetch mints its own token) on a fresh browser session, closing it
        on exit."""
        browser = self._get_browser()
        try:
            page = browser.get_page(ORDERS_URL)
            # Let the app shell settle so Clerk's session state is live.
            page.wait_for_timeout(1500)
            yield page
        finally:
            browser.close()
            self._browser = None

    def _get_json(self, path: str) -> Any:
        with self._page() as page:
            result = page.evaluate(FETCH_JS, [path])
        if not isinstance(result, dict):
            raise ClientError(
                f"Unexpected response evaluating fetch for {path}: {result!r}"
            )
        if not result.get("ok"):
            raise ClientError(
                f"trainee.digital API request to {path} failed "
                f"(HTTP {result.get('status')}): {str(result.get('body'))[:300]}"
            )
        return result.get("body")

    def fetch_orders(self) -> Any:
        """Raw GET /api/orders body (a list). Never cached: the command and
        auth seams each need the current feed."""
        return self._get_json(ORDERS_PATH)

    def fetch_profile(self) -> Dict[str, Any]:
        """Raw GET /api/me/profile body -- the live auth round-trip."""
        body = self._get_json(PROFILE_PATH)
        if not isinstance(body, dict):
            raise ClientError(
                f"GET {PROFILE_PATH} returned {type(body).__name__}, expected an object."
            )
        return body

    @cached
    def list_tasks(self, limit: int = 100) -> List[dict]:
        """Open orders from GET /api/orders, normalized."""
        rows = normalize_orders(self.fetch_orders())
        return rows[:limit]

    def get_task(self, task_id: str) -> dict:
        """Full record for one order by its ``id`` from GET /api/orders/<id>."""
        if not isinstance(task_id, str) or not task_id.strip():
            raise ClientError("An order id is required.")
        path = f"{ORDERS_PATH}/{task_id}"
        body = self._get_json(path)
        if not isinstance(body, dict):
            raise ClientError(
                f"GET {path} returned {type(body).__name__}, expected an object."
            )
        return normalize_order_detail(body, task_id)


_client: Optional[TraineeDigitalClient] = None


def get_client(profile: Optional[str] = None) -> TraineeDigitalClient:
    """Get or create the global TraineeDigital client instance (per profile)."""
    global _client
    key = profile or "_default"
    if _client is None or getattr(_client, "_profile_key", None) != key:
        _client = TraineeDigitalClient(profile)
        _client._profile_key = key  # type: ignore[attr-defined]
    return _client
