"""Mercor client using BrowserAutomation from cli_tools_shared.

The worker surface (https://work.mercor.com/explore) is a Next.js SPA whose
role listings come from an internal JSON API on a separate host,
`GET https://aws.api.mercor.com/work/listings-explore-page`, authorized by the
Firebase ID-token JWT that the app keeps in the `token` cookie on
work.mercor.com (see browser.py).

Validated live 2026-09-03:
  - The endpoint answers a plain HTTPS GET with `Authorization: Bearer <token>`
    plus browser-like `Origin`/`Referer`/`User-Agent` headers and
    `X-Client-IP: true` -- HTTP 200, `application/json`,
    `{"listings": [<402 objects>]}`. A same-browser cross-origin fetch from the
    HEADLESS harness is rejected (`TypeError: Failed to fetch`) even though the
    same fetch works in real Chrome, so the CLI does NOT fetch through the
    page: it boots the authenticated profile headlessly only long enough to
    read a fresh session token from the `token` cookie (the Explore page load
    also lets Firebase restore the session and re-mint that cookie), then makes
    the API GET itself over HTTPS.
  - Response has no cursor: one call returns the full catalog the Explore
    surface filters and renders.

The token is CLI-managed runtime auth state (read from the CLI's own browser
profile and sent straight to Mercor's API); it is never printed or stored
anywhere else.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .browser import MercorBrowser
from .config import get_config
from .parsers import normalize_listing, normalize_listings

LISTINGS_URL = "https://aws.api.mercor.com/work/listings-explore-page"
EXPLORE_PAGE_URL = "https://work.mercor.com/explore"
TOKEN_JS = (
    "() => (document.cookie.match(/(?:^|; )token=([^;]*)/) || [])[1] || ''"
)
# Headers Mercor's API expects from the worker app (validated live: without a
# browser-like Origin/Referer/UA the request still succeeds, but these match
# the site's own traffic and are harmless to send).
SESSION_SETTLE_MS = 2500
MAX_ATTEMPTS = 3
BASE_DELAY_SECONDS = 2.0
RETRY_STATUSES = {429, 500, 502, 503, 504}
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
)


class MercorClient:
    """Client that uses BrowserAutomation to drive Mercor."""

    def __init__(self, profile: Optional[str] = None):
        self.config = get_config(profile)
        self._browser: Optional[MercorBrowser] = None

    def _get_browser(self) -> MercorBrowser:
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def close(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    def _read_session_token(self) -> str:
        """Boot the authenticated profile and read a fresh `token` cookie.

        Loading the Explore page also lets Firebase restore the persisted
        session and re-mint the cookie when the previous one expired, so a
        token read here is as fresh as the profile's session.
        """
        browser = self._get_browser()
        try:
            page = browser.get_page(EXPLORE_PAGE_URL)
            page.wait_for_timeout(SESSION_SETTLE_MS)
            token = page.evaluate(TOKEN_JS)
        finally:
            browser.close()
            self._browser = None
        if not isinstance(token, str) or not token:
            raise ClientError(
                "No Mercor session token was found after loading the Explore "
                "page. Run 'mercor auth login' to authenticate this profile."
            )
        return token

    def _http_get_listings(self, token: str) -> Dict[str, Any]:
        """GET the listings API over HTTPS with one retry loop."""
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Authorization": f"Bearer {token}",
            "X-Client-IP": "true",
            "Origin": "https://work.mercor.com",
            "Referer": "https://work.mercor.com/",
            "User-Agent": _UA,
        }
        last_error: Optional[Exception] = None
        for attempt in range(MAX_ATTEMPTS):
            request = urllib.request.Request(LISTINGS_URL, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ClientError(
                        f"{LISTINGS_URL} returned {type(payload).__name__}, "
                        "expected an object."
                    )
                return payload
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code == 401:
                    raise ClientError(
                        "Mercor API rejected the session token (HTTP 401). "
                        "Run 'mercor auth login' to refresh the session."
                    ) from exc
                if exc.code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS - 1:
                    raise ClientError(
                        f"Mercor API request to {LISTINGS_URL} failed "
                        f"(HTTP {exc.code}): {exc.reason}"
                    ) from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt == MAX_ATTEMPTS - 1:
                    raise ClientError(
                        f"Mercor API request to {LISTINGS_URL} failed after "
                        f"{MAX_ATTEMPTS} attempts: {exc}"
                    ) from exc
            time.sleep(BASE_DELAY_SECONDS * (2 ** attempt))
        raise ClientError(
            f"Mercor API request to {LISTINGS_URL} failed: {last_error}"
        )

    def fetch_listings(self) -> Dict[str, Any]:
        """Raw listings body: ``{"listings": [...]}``. Never cached: the auth
        `test_connection` seam uses it as the live round-trip."""
        return self._http_get_listings(self._read_session_token())

    @cached
    def list_tasks(self, limit: int = 1000) -> List[dict]:
        """Role listings from the Mercor Explore worker surface.

        The Explore endpoint is cursorless and returns the full catalog in one
        call, so the default limit (1000) exceeds the catalog rather than
        silently truncating it.
        """
        body = self._http_get_listings(self._read_session_token())
        rows = normalize_listings(body.get("listings"))
        return rows[:limit]

    def get_task(self, task_id: str) -> dict:
        """Full record for one listing by its `id` (the `listingId`).

        Mercor exposes no separate per-listing JSON endpoint for the Explore
        surface -- the Explore page filters the same full catalog client-side,
        and the detail drawer reads the same record -- so this reads the same
        fetch and returns the matching entry in full.
        """
        body = self._http_get_listings(self._read_session_token())
        raw_list = body.get("listings")
        if not isinstance(raw_list, list):
            raw_list = []
        for raw in raw_list:
            if isinstance(raw, dict) and raw.get("listingId") == task_id:
                return normalize_listing(raw)
        raise ClientError(
            f"No Mercor listing with id {task_id!r}. The Explore surface "
            f"currently returns {len(raw_list)} listing(s)."
        )


_clients: dict = {}


def get_client(profile: Optional[str] = None) -> MercorClient:
    """Get or create the Mercor client instance for a profile."""
    key = profile or "_default"
    if key not in _clients:
        _clients[key] = MercorClient(profile=profile)
    return _clients[key]
