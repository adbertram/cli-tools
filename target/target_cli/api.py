"""Target internal JSON API (redsky) client.

Reads (search / product detail / fulfillment / store lookup) run as plain httpx
calls against ``redsky.target.com`` using the ``_tgt_token`` + ``_tgt_session``
cookies captured by a real browser (see ``browser.py:prime_redsky`` and
``session.py``). No browser is launched for reads.

Fail loud: a missing or expired session, a bot-wall (403), or any non-200 raises
``ClientError`` with the exact action to take. There is no DOM fallback.
"""

from typing import Optional

import httpx
from cli_tools_shared.exceptions import ClientError

from .session import RedskySession, load_session

# Static public web key embedded in target.com's __NEXT_DATA__ (verified live).
REDSKY_KEY = "9f36aeafbe60771e321a7cc95a78140772ab3e96"
REDSKY_BASE = "https://redsky.target.com/redsky_aggregations/v1/web"

# A normal Chrome UA; redsky gates on the _tgt_* cookies, not the UA, but a real
# UA keeps the request indistinguishable from the browser that minted the token.
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)

_REAUTH_HINT = "Run `target auth login` (or `target session refresh`) to capture a fresh redsky session."


class RedskyAPI:
    """Thin redsky HTTP client bound to a captured browser session."""

    def __init__(self, session: RedskySession):
        self._session = session
        self._http = httpx.Client(
            base_url=REDSKY_BASE,
            cookies=session.cookies,
            headers={"accept": "application/json", "user-agent": _UA},
            timeout=30.0,
        )

    def close(self) -> None:
        self._http.close()

    # ---- resolved store/zip context (session capture geo, overridable) ----
    def _store(self, store_id: Optional[str]) -> str:
        return str(store_id or self._session.store_id)

    def _zip(self, zip_code: Optional[str]) -> str:
        return str(zip_code or self._session.zip)

    def _get(self, path: str, params: dict) -> dict:
        params["key"] = REDSKY_KEY
        params["channel"] = "WEB"
        params["visitor_id"] = self._session.visitor_id
        try:
            resp = self._http.get(path, params=params)
        except httpx.HTTPError as exc:
            raise ClientError(f"redsky request failed: {exc}") from exc
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (401, 403):
            raise ClientError(
                f"redsky rejected the request (HTTP {resp.status_code}) -- the session is "
                f"expired or bot-flagged. {_REAUTH_HINT}"
            )
        raise ClientError(
            f"redsky {path} returned HTTP {resp.status_code}: {resp.text[:200]}"
        )

    def search(
        self, keyword: str, *, count: int = 24, offset: int = 0,
        store_id: Optional[str] = None, zip_code: Optional[str] = None,
    ) -> dict:
        store = self._store(store_id)
        return self._get(
            "/plp_search_v2",
            {
                "count": str(count),
                "offset": str(offset),
                "keyword": keyword,
                "page": f"/s/{keyword}",
                "platform": "desktop",
                "pricing_store_id": store,
                "store_ids": store,
                "zip": self._zip(zip_code),
                "new_search": "true",
                "default_purchasability_filter": "true",
                "include_sponsored": "true",
                "include_dmc_dmr": "true",
                "spellcheck": "true",
            },
        )

    def product_detail(
        self, tcin: str, *, store_id: Optional[str] = None
    ) -> dict:
        store = self._store(store_id)
        return self._get(
            "/pdp_client_v1",
            {
                "tcin": tcin,
                "is_bot": "false",
                "store_id": store,
                "pricing_store_id": store,
                "has_pricing_store_id": "true",
                "has_financing_options": "false",
                "has_size_context": "true",
                "latency_type": "big_data",
                "page": f"/p/A-{tcin}",
            },
        )

    def fulfillment(
        self, tcin: str, *, store_id: Optional[str] = None, zip_code: Optional[str] = None
    ) -> dict:
        store = self._store(store_id)
        return self._get(
            "/product_fulfillment_v1",
            {
                "tcin": tcin,
                "store_id": store,
                "pricing_store_id": store,
                "required_store_id": store,
                "has_required_store_id": "true",
                "scheduled_delivery_store_id": store,
                "zip": self._zip(zip_code),
                "page": f"/p/A-{tcin}",
            },
        )

    def nearby_stores(self, zip_code: str, *, limit: int = 20, within: int = 100) -> dict:
        return self._get(
            "/nearby_stores_v1",
            {"limit": str(limit), "within": str(within), "place": zip_code},
        )

    def store_location(self, store_id: str) -> dict:
        return self._get("/store_location_v1", {"store_id": store_id})


def get_redsky_api(config) -> RedskyAPI:
    """Load the cached redsky session and return a client, or fail loudly."""
    session = load_session(config)
    if session is None:
        raise ClientError(f"No redsky session captured yet. {_REAUTH_HINT}")
    if session.expired:
        raise ClientError(
            f"redsky session is stale (~{session.age_seconds / 3600:.1f}h old). {_REAUTH_HINT}"
        )
    return RedskyAPI(session)
