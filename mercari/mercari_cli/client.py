"""Mercari client driving the authenticated web app via BrowserAutomation.

Why the "capture the app's own request" strategy
------------------------------------------------
Mercari's internal GraphQL API (`/v1/api`) authenticates each request with a
short-lived `authorization` JWT plus device-bound headers (`x-csrf-token`,
`x-socure-device-token`) that Apollo attaches inside the page. A raw
in-page `fetch(url, {credentials:'include'})` replay returns HTTP 401 because
those headers are NOT reproducible outside Apollo's link chain (verified
live). So instead of replaying the API, we let the logged-in web app issue its
own authenticated request and capture the JSON response via a `fetch`
interceptor injected before a client-side (SPA) route change. This reuses the
app's real auth and returns full-fidelity structured data — no DOM scraping,
no token extraction.

Operations (validated against the live session):
  - list   -> `userItemsQuery`   (data.userItems.items[] + pagination)
              status map: active->on_sale, inactive->stop, complete->sold_out
  - get    -> `productQuery`      (data.item)
  - search -> `searchFacetQuery`  (data.search.itemsList) — public search;
              filters are passed as /search URL params that the SPA translates
              into the GraphQL criteria (all mappings validated live).
"""
import json
import re
import time
from typing import Callable, List, Optional
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .browser import MercariBrowser
from .config import get_config
from .parsers import normalize_item_detail, normalize_items


class MercariChallengeError(ClientError):
    """Mercari requires a human verification action."""


class MercariItemNotFoundError(ClientError):
    """Mercari returned no item for the requested item id."""

# Active/inactive/complete map to userItemsQuery status values. Validated live.
STATUS_MAP = {
    "active": ("active", "on_sale"),
    "inactive": ("inactive", "stop"),
    "complete": ("complete", "sold_out"),
}

# Public search filter mappings — every value validated live against the
# searchFacetQuery criteria and result set. Multi-value params MUST be repeated
# in the URL (comma-joined values break the SPA parser).
SEARCH_STATUS_MAP = {"on_sale": [1], "sold": [2, 3]}
SEARCH_CONDITION_MAP = {"new": 1, "like_new": 2, "good": 3, "fair": 4, "poor": 5}
# The Source-CLI Sort Standard field -> Mercari `sortBy` code mapping lives in
# main.py (`_resolve_sort`). The numeric sortBy code arrives here already
# resolved; `sort_by=None` omits the param (best-match/relevance). `sortOrder`
# is a no-op — direction is baked into each sortBy code (verified live: a
# sortOrder URL param does not re-trigger the searchFacetQuery).


def build_search_params(
    keyword: str,
    status: Optional[str] = None,
    condition: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    sort_by: Optional[int] = None,
    category_ids: Optional[List[int]] = None,
    brand_ids: Optional[List[int]] = None,
) -> List[tuple]:
    """Build the ``/search`` URL query params the SPA translates into the
    ``searchFacetQuery`` criteria (validated live; see README "Data source").

    ``sort_by`` is a resolved numeric Mercari ``sortBy`` code (e.g. 2 = newest,
    3 = price low->high, 4 = price high->low). ``None`` omits the param, which
    Mercari treats as best-match/relevance. Prices are US dollars converted to
    the API's cent unit. Multi-value params are repeated (comma-joined values
    break the SPA parser).
    """
    if status is not None and status not in SEARCH_STATUS_MAP:
        raise ClientError(
            f"Unknown status {status!r}. Choose from: {', '.join(SEARCH_STATUS_MAP)}."
        )
    if condition is not None and condition not in SEARCH_CONDITION_MAP:
        raise ClientError(
            f"Unknown condition {condition!r}. Choose from: {', '.join(SEARCH_CONDITION_MAP)}."
        )

    params: List[tuple] = [("keyword", keyword)]
    if status is not None:
        params += [("itemStatuses", str(v)) for v in SEARCH_STATUS_MAP[status]]
    if condition is not None:
        params.append(("itemConditions", str(SEARCH_CONDITION_MAP[condition])))
    if min_price is not None:
        params.append(("minPrice", str(int(round(min_price * 100)))))
    if max_price is not None:
        params.append(("maxPrice", str(int(round(max_price * 100)))))
    if sort_by is not None:
        params.append(("sortBy", str(sort_by)))
    params += [("categoryIds", str(c)) for c in (category_ids or [])]
    params += [("brandIds", str(b)) for b in (brand_ids or [])]
    return params

SHELL_URL = "https://www.mercari.com/mypage/"
HOME_URL = "https://www.mercari.com/"
ITEM_ROUTE = "/us/item/{item_id}/"
LISTINGS_ROUTE = "/mypage/listings/{suffix}/"

_CHALLENGE_MARKERS = ("just a moment", "security verification", "verify you are human")
_ITEM_ID_RE = re.compile(r"(m\d{6,})")

# Idempotent fetch interceptor: patches window.fetch once, records every
# /v1/api response into window.__mc, and (re)starts the buffer on each call.
_INTERCEPTOR = r"""
() => {
  window.__mc = [];
  if (window.__mcPatched) return true;
  window.__mcPatched = true;
  const of = window.fetch;
  window.fetch = async (...a) => {
    const u = (a[0] && a[0].url) || a[0];
    const r = await of(...a);
    try {
      if (String(u).includes('/v1/api')) {
        const b = await r.clone().text();
        (window.__mc = window.__mc || []).push({u: String(u), s: r.status, b: String(b || '')});
      }
    } catch (e) {}
    return r;
  };
  return true;
}
"""

_SPA_PUSH = r"""
(path) => {
  if (window.next && window.next.router && window.next.router.push) {
    window.next.router.push(path);
    return true;
  }
  return false;
}
"""


def _op_name(url: str) -> str:
    try:
        return parse_qs(urlparse(url).query).get("operationName", [""])[0]
    except Exception:
        return ""


def _variables(url: str) -> dict:
    try:
        raw = parse_qs(urlparse(url).query).get("variables", ["{}"])[0]
        return json.loads(unquote(raw))
    except Exception:
        return {}


def _normalize_item_id(value: str) -> str:
    match = _ITEM_ID_RE.search(value or "")
    if not match:
        raise ClientError(
            f"Invalid Mercari item id {value!r}. Expected an id like 'm12345678901' "
            "or an item URL."
        )
    return match.group(1)


class MercariClient:
    """Drives the authenticated Mercari web app and captures its API responses."""

    def __init__(self):
        self.config = get_config()
        self._browser: Optional[MercariBrowser] = None

    def _get_browser(self) -> MercariBrowser:
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def close(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    # ---------------- page / auth plumbing ----------------

    def _app_shell(self, url: str):
        """Return an app shell page with the Next.js router ready.

        Navigates to ``url``, waits past any Cloudflare interstitial, and
        confirms the client-side router is available for SPA navigation. Does
        NOT assert authentication (used for the public search surface).
        """
        page = self._get_browser().get_page(url)
        self._wait_ready(page)
        has_router = page.evaluate(
            "() => !!(window.next && window.next.router && window.next.router.push)"
        )
        if not has_router:
            raise ClientError(
                "Mercari web app router is unavailable; cannot drive navigation."
            )
        return page

    def _authenticated_shell(self):
        """Return the /mypage/ shell page, proving the session is authenticated.

        /mypage/ redirects to /login/ when logged out; a visible login form (or
        a /login path) means the session is not authenticated.
        """
        page = self._app_shell(SHELL_URL)
        on_login = page.evaluate(
            """() => document.querySelector('input[data-testid="PasswordInput"]') !== null
                     || /\\/login|\\/signup/.test(location.pathname)"""
        )
        if on_login:
            raise ClientError(
                "Not authenticated with Mercari. Run 'mercari auth login' and complete "
                "the email verification code, then retry."
            )
        return page

    @staticmethod
    def _page_info(page) -> dict:
        return page.evaluate(
            """() => {
                const title = (document.title || '').toLowerCase();
                const body = (document.body && document.body.innerText || '');
                return {
                    title,
                    bodyLen: body.length,
                    routerReady: !!(window.next && window.next.router && window.next.router.push),
                    challenged: !!document.querySelector(
                        '#cf-challenge-running, .cf-browser-verification, '
                        + 'iframe[src*="challenges.cloudflare.com"], '
                        + 'iframe[src*="recaptcha"], iframe[src*="hcaptcha"]'
                    ) || /just a moment|security verification|verify you are human|checking your browser|ray id/i.test(title + ' ' + body),
                };
            }"""
        )

    @staticmethod
    def _raise_on_challenge(info: dict) -> None:
        if info["challenged"] or any(
            marker in info["title"] for marker in _CHALLENGE_MARKERS
        ):
            raise MercariChallengeError(
                "Mercari presented a human verification challenge. "
                "Run 'mercari auth login' to refresh the saved browser session."
            )

    @classmethod
    def _wait_ready(cls, page, timeout: int = 60) -> None:
        deadline = time.monotonic() + timeout
        last_info = {}
        while time.monotonic() < deadline:
            info = cls._page_info(page)
            last_info = info
            cls._raise_on_challenge(info)
            if info["routerReady"]:
                return
            time.sleep(3)
        raise ClientError(
            "Mercari web app router did not become ready within "
            f"{timeout} seconds (title={last_info.get('title', '')!r}, "
            f"body_length={last_info.get('bodyLen', 0)})."
        )

    def _capture(
        self,
        page,
        route: str,
        operation: str,
        accept: Callable[[dict], bool],
        timeout: int = 45,
    ) -> List[dict]:
        """Inject the interceptor, push a client-side route, and return the
        parsed JSON bodies of matching ``operation`` responses."""
        page.evaluate(_INTERCEPTOR)
        if not page.evaluate(_SPA_PUSH, route):
            raise ClientError("Mercari SPA navigation failed; router unavailable.")
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._raise_on_challenge(self._page_info(page))
            matched = self._read_matches(page, operation, accept)
            if matched:
                return matched
            time.sleep(2)
        return []

    @staticmethod
    def _read_matches(page, operation: str, accept: Callable[[dict], bool]) -> List[dict]:
        out = []
        for call in page.evaluate("() => window.__mc || []"):
            if _op_name(call["u"]) != operation or not accept(_variables(call["u"])):
                continue
            try:
                out.append(json.loads(call["b"]))
            except (ValueError, TypeError):
                continue
        return out

    # ---------------- public API ----------------

    @cached
    def list_items(self, status: str = "active", limit: int = 100) -> List[dict]:
        """List the authenticated seller's own listings for a status.

        status: active | inactive | complete
        Returns the userItems.items[] records verbatim (id/url added).
        """
        if status not in STATUS_MAP:
            raise ClientError(
                f"Unknown status {status!r}. Choose from: {', '.join(STATUS_MAP)}."
            )
        suffix, gql_status = STATUS_MAP[status]

        def accept(variables: dict) -> bool:
            return variables.get("userItemsInput", {}).get("status") == gql_status

        page = self._authenticated_shell()
        route = LISTINGS_ROUTE.format(suffix=suffix)
        bodies = self._capture(page, route, "userItemsQuery", accept)
        if not bodies:
            raise ClientError(
                f"Timed out capturing Mercari listings for status '{status}'."
            )
        items, has_next = self._merge_pages(bodies)

        scrolls = 0
        while len(items) < limit and has_next and scrolls < 40:
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(3)
            bodies = self._read_matches(page, "userItemsQuery", accept)
            merged, has_next = self._merge_pages(bodies)
            if len(merged) <= len(items):
                break
            items = merged
            scrolls += 1

        return normalize_items(items[:limit])

    def get_item(self, item_id: str) -> dict:
        """Get full detail for a single listing/item by id or URL.

        Mercari item pages are PUBLIC (any item URL is viewable logged-out), so
        this drives the public app shell — the same surface as ``search`` — and
        never gates on a seller login. It only needs the persistent
        ``cf_clearance`` cookie to clear Cloudflare, so item detail keeps working
        in headless/automated runs even after the seller session expires. Only
        ``list`` (the seller's OWN listings) requires the authenticated shell.
        """
        return normalize_item_detail(self._fetch_item(item_id))

    def get_items(self, item_ids: List[str]) -> List[dict]:
        """Get many public items through one Mercari app shell."""
        results = []
        page = None
        for requested_id in item_ids:
            try:
                normalized_id = _normalize_item_id(requested_id)
                if page is None:
                    page = self._app_shell(HOME_URL)
                item = normalize_item_detail(
                    self._fetch_item_from_page(page, normalized_id)
                )
            except MercariChallengeError:
                raise
            except ClientError as exc:
                results.append(
                    {
                        "item_id": requested_id,
                        "status": "error",
                        "error_kind": (
                            "not_found"
                            if isinstance(exc, MercariItemNotFoundError)
                            else "unreadable"
                        ),
                        "error": str(exc),
                    }
                )
            else:
                results.append(
                    {
                        "item_id": requested_id,
                        "status": "ok",
                        "item": item,
                    }
                )
        return results

    @cached
    def _fetch_item(self, item_id: str) -> dict:
        """Fetch raw item detail and cache only the upstream response."""
        normalized_id = _normalize_item_id(item_id)

        page = self._app_shell(HOME_URL)
        return self._fetch_item_from_page(page, normalized_id)

    def _fetch_item_from_page(self, page, normalized_id: str) -> dict:
        """Fetch one raw item through an existing Mercari app shell."""

        def accept(variables: dict) -> bool:
            return variables.get("id") == normalized_id

        route = ITEM_ROUTE.format(item_id=normalized_id)
        bodies = self._capture(page, route, "productQuery", accept)
        if not bodies:
            raise ClientError(
                f"Timed out capturing Mercari item '{normalized_id}'."
            )
        data = bodies[0].get("data") or {}
        item = data.get("item")
        if not item:
            raise MercariItemNotFoundError(
                f"Mercari item '{normalized_id}' not found."
            )
        return item

    @cached
    def search_items(
        self,
        keyword: str,
        limit: int = 100,
        status: Optional[str] = None,
        condition: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        sort_by: Optional[int] = None,
        category_ids: Optional[List[int]] = None,
        brand_ids: Optional[List[int]] = None,
    ) -> List[dict]:
        """Search OTHER sellers' public Mercari listings.

        Filters are passed as /search URL params that the SPA translates into
        the searchFacetQuery GraphQL criteria (validated live). ``sort_by`` is a
        resolved numeric Mercari ``sortBy`` code (see main._resolve_sort);
        ``None`` omits it (best-match/relevance). Prices in
        --min-price/--max-price are US dollars and converted to the API's cent
        unit. Item prices in results remain in cents (API-faithful).
        """
        params = build_search_params(
            keyword,
            status=status,
            condition=condition,
            min_price=min_price,
            max_price=max_price,
            sort_by=sort_by,
            category_ids=category_ids,
            brand_ids=brand_ids,
        )
        route = "/search/?" + urlencode(params)

        def accept(variables: dict) -> bool:
            return (variables.get("criteria") or {}).get("query") == keyword

        page = self._app_shell(HOME_URL)
        bodies = self._capture(page, route, "searchFacetQuery", accept)
        if not bodies:
            raise ClientError(f"Timed out capturing Mercari search for {keyword!r}.")
        items = self._merge_search(bodies)

        scrolls = 0
        while len(items) < limit and scrolls < 40:
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(3)
            merged = self._merge_search(self._read_matches(page, "searchFacetQuery", accept))
            if len(merged) <= len(items):
                break
            items = merged
            scrolls += 1

        return normalize_items(items[:limit])

    @staticmethod
    def _merge_search(bodies: List[dict]) -> List[dict]:
        """Concatenate searchFacetQuery itemsList across pages, deduped by id."""
        items: List[dict] = []
        seen = set()
        for body in bodies:
            search = (body.get("data") or {}).get("search") or {}
            for item in search.get("itemsList") or []:
                item_id = item.get("id")
                if item_id in seen:
                    continue
                seen.add(item_id)
                items.append(item)
        return items

    @staticmethod
    def _merge_pages(bodies: List[dict]):
        """Merge userItemsQuery response pages in page order, deduped.

        Returns (items, has_next). Each body is
        {"data": {"userItems": {"items": [...], "pagination": {...}}}}.
        """
        by_page = {}
        for body in bodies:
            user_items = (body.get("data") or {}).get("userItems") or {}
            pagination = user_items.get("pagination") or {}
            page_no = pagination.get("currentPage", 1)
            by_page[page_no] = {
                "items": user_items.get("items") or [],
                "has_next": bool(pagination.get("hasNext")),
            }
        items: List[dict] = []
        has_next = False
        for page_no in sorted(by_page):
            items.extend(by_page[page_no]["items"])
            has_next = by_page[page_no]["has_next"]
        return items, has_next


_client: Optional[MercariClient] = None


def get_client() -> MercariClient:
    """Get or create the global Mercari client instance."""
    global _client
    if _client is None:
        _client = MercariClient()
    return _client
