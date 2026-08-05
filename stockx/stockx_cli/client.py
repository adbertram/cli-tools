"""StockX client driving the live web session's own `/api/graphql` endpoint.

Why an in-page fetch instead of a standalone HTTP client
--------------------------------------------------------
StockX's public REST API (developer.stockx.com) is an approval-gated seller and
catalog program, not a general search API. The web app instead posts every
browse and product query to ``POST https://stockx.com/api/graphql``, behind
Cloudflare. This client runs those requests INSIDE a live stockx.com page via
``page.evaluate()``, so each one carries the real browser's Cloudflare
clearance, cookies, and network stack. Everything below was validated live
against stockx.com during CLI creation.

Persisted queries
-----------------
StockX uses Apollo **automatic persisted queries**: the request body carries
only ``operationName``, ``variables``, and
``extensions.persistedQuery.sha256Hash`` — never the query text. Sending our
own query document is rejected by Cloudflare with HTTP 403 (verified), so the
hash is mandatory and cannot be replaced with a hand-written document.

Those hashes are build artifacts that change whenever StockX ships a new web
bundle, so nothing here hardcodes one. :meth:`StockxClient._persisted_hash`
reads the current hash out of the app's own outgoing request by installing a
``fetch`` interceptor and driving one client-side route change. The result is
cached against StockX's own ``appVersion`` (from ``__NEXT_DATA__``), so a new
StockX deploy invalidates the cache and the hash is captured again — one
execution path, no stale-hash recovery branch.

Request headers
---------------
``/api/graphql`` returns HTTP 404 for a bare ``content-type`` request and HTTP
200 once the app's client headers are present (verified). Every value comes
from the live page's ``__NEXT_DATA__`` ``pageProps.req`` block —
``appVersion``, ``stockx_device_id``, and ``sessionId`` — so nothing is minted
or guessed here.

Verified vocabulary
-------------------
Filters are ``{id, selectedValues}`` entries. Each id below was confirmed by
StockX's own echo (``browse.filtersConfig`` reports the applied selection):

  | CLI option        | filter id           | verified values                       |
  |-------------------|---------------------|---------------------------------------|
  | ``--brand``       | ``brand``           | slugs, e.g. ``nike``, ``adidas``      |
  | ``--gender``      | ``gender``          | men, women, unisex, kids              |
  | ``--category``    | ``category``        | sneakers, apparel, accessories, ...   |
  | ``--color``       | ``color``           | black, white, multi, blue, ...        |
  | ``--activity``    | ``activity``        | basketball, running, soccer, ...      |
  | ``--below-retail``| ``below-retail``    | ``true``                              |
  | ``--xpress-ship`` | ``xpress-ship``     | ``true``                              |
  | ``--min-price`` / ``--max-price`` | ``lowest-ask-range`` | two values ``[min, max]`` |

**StockX silently ignores unknown filter ids, unknown filter values, and
unknown sort ids**, returning the unfiltered default instead of an error
(verified: ``brand=Nike`` display-case and ``sort=bogus_sort`` both echoed no
selection). Because a silently dropped filter is worse than a failure, every
option is validated here against the vocabulary StockX itself publishes.
"""

import json
import time
from typing import Dict, List, Optional
from urllib.parse import urlparse

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.http_session import (
    DEFAULT_REQUESTS_BASE_DELAY,
    DEFAULT_REQUESTS_JITTER,
    DEFAULT_REQUESTS_MAX_DELAY,
    DEFAULT_REQUESTS_MAX_RETRIES,
    DEFAULT_REQUESTS_RETRYABLE_STATUS_CODES,
    RequestsRetryPolicy,
)

from .config import get_config
from .parsers import normalize_market, normalize_product, normalize_products

GRAPHQL_PATH = "/api/graphql"

# StockX's own web-app page size, and the paging ceiling this client will walk
# before giving up on reaching `--limit`. StockX caps a result window at 1000
# products (verified), which 25 pages of 40 covers exactly.
PAGE_SIZE = 40
MAX_PAGES = 25

# Seed used only to make StockX's own app fire the operation whose persisted
# query hash we need to read. Any catalog term works; this one is stable.
HASH_SEED_QUERY = "nike"

SEARCH_OPERATION = "getDiscoveryData"
PRODUCT_OPERATION = "GetProduct"
MARKET_OPERATION = "GetMarketData"

# Server-published filter vocabularies (browse.filtersConfig), captured live.
GENDER_VALUES = ("men", "women", "unisex", "kids")
CATEGORY_VALUES = (
    "sneakers",
    "apparel",
    "accessories",
    "collectibles",
    "shoes",
    "trading-cards",
)
COLOR_VALUES = (
    "black",
    "white",
    "multi",
    "blue",
    "green",
    "grey",
    "red",
    "pink",
    "brown",
    "orange",
    "yellow",
    "purple",
)

# ---------------------------------------------------------------------------
# Sort (Source-CLI Sort Standard)
# ---------------------------------------------------------------------------
# StockX bakes direction into the sort id itself. `sort.order` exists in the
# schema as a `BrowseSortOrder` enum, but supplying it alongside a directional
# id silently reverts the applied sort to `featured` (verified live), so it is
# never sent. No StockX sort publishes a reverse order, so `--desc` is rejected
# with a message naming the alternative rather than silently ignored.
DEFAULT_SORT = "featured"

# user value -> (natural api token [no --desc], reversed api token [--desc])
_SORT_DIRECTIONS = {
    "featured": ("featured", None),
    "lowest-ask": ("lowest_ask", None),
    "highest-bid": ("highest_bid", None),
    "release-date": ("release_date", None),
}
SORT_VALUES = tuple(_SORT_DIRECTIONS)

# StockX's own getDiscoveryData variables, minus the per-request parts this
# client sets (query, page, filters, sort). Sent verbatim so the persisted
# query receives the variable shape it was built for.
_BROWSE_VARIABLES = {
    "country": "US",
    "currency": "USD",
    "flow": "SEARCH_RESULTS",
    "market": "US",
    "includeProcessingFeeForPricing": True,
    "enableMysteryBox": True,
    "experiments": {
        "ads": {"enabled": True},
        "dynamicFilter": {"enabled": True},
        "dynamicFilterDefinitions": {"enabled": True},
        "multiselect": {"enabled": True},
        "openSearch": {"enabled": False},
        "unifiedDiscovery": {"enabled": False},
        "enableMysteryBox": {"enabled": True},
    },
    "enableForYouFeed": False,
    "enableListings": True,
    "enableLive": False,
}

# Reads StockX's client headers out of the live page and posts the persisted
# query with them. Every header value comes from the page, never from us.
_FETCH_JS = """async (opts) => {
    const nextData = document.querySelector('#__NEXT_DATA__');
    if (!nextData) {
        return {status: 0, statusText: 'no __NEXT_DATA__ on page', body: ''};
    }
    const req = JSON.parse(nextData.textContent).props.pageProps.req;
    const resp = await fetch(opts.path, {
        method: 'POST',
        credentials: 'include',
        headers: {
            'accept': 'application/json',
            'content-type': 'application/json',
            'accept-language': 'en-US',
            'App-Platform': 'Iron',
            'App-Version': req.appVersion,
            'apollographql-client-name': 'Iron',
            'apollographql-client-version': req.appVersion,
            'x-stockx-device-id': req.stockx_device_id,
            'x-stockx-session-id': req.sessionId,
            'selected-country': 'US',
            'x-operation-name': opts.operationName,
        },
        body: JSON.stringify({
            operationName: opts.operationName,
            variables: opts.variables,
            extensions: {persistedQuery: {version: 1, sha256Hash: opts.hash}},
        }),
    });
    const text = await resp.text();
    return {
        status: resp.status,
        statusText: resp.statusText,
        retryAfter: resp.headers.get('retry-after'),
        body: text,
    };
}"""

# Records the persisted-query hash off the app's own outgoing request.
_INSTALL_INTERCEPTOR_JS = """() => {
    window.__stockxHashes = {};
    const original = window.fetch;
    window.fetch = function (input, init) {
        const url = typeof input === 'string' ? input : (input && input.url);
        if (init && init.body && /graphql/i.test(String(url))) {
            try {
                const parsed = JSON.parse(init.body);
                const hash = parsed.extensions
                    && parsed.extensions.persistedQuery
                    && parsed.extensions.persistedQuery.sha256Hash;
                if (parsed.operationName && hash) {
                    window.__stockxHashes[parsed.operationName] = hash;
                }
            } catch (err) { /* non-JSON body: not a GraphQL call */ }
        }
        return original.apply(this, arguments);
    };
    return true;
}"""

_APP_VERSION_JS = """() => {
    const nextData = document.querySelector('#__NEXT_DATA__');
    if (!nextData) { return null; }
    return JSON.parse(nextData.textContent).props.pageProps.req.appVersion;
}"""

# stockx.com serves its app payload a beat after navigation returns, so a single
# immediate read intermittently sees an empty document (observed live on
# back-to-back CLI runs against the same profile). Poll for readiness instead.
_APP_READY_ATTEMPTS = 10
_APP_READY_POLL_MS = 1500


class SortError(ClientError):
    """Raised for an invalid ``--sort``/``--desc`` combination."""


def resolve_sort(sort: str, desc: bool = False) -> str:
    """Resolve a ``(--sort, --desc)`` pair to StockX's API ``sort`` id.

    Raises :class:`SortError` with a clear, valid-values message on any
    unrecognized value or unsupported direction. Never silently falls back,
    because StockX ignores an unknown sort id and returns featured order.
    """
    key = (sort or "").strip().lower()
    if key not in _SORT_DIRECTIONS:
        raise SortError(
            f"Invalid --sort '{sort}'. Valid values: {', '.join(SORT_VALUES)}."
        )
    natural, reversed_token = _SORT_DIRECTIONS[key]
    if desc:
        if reversed_token is None:
            raise SortError(
                f"--desc is not supported with --sort {key}: StockX publishes no "
                "reverse order for any sort. For descending price use "
                "--sort highest-bid instead of --sort lowest-ask --desc."
            )
        return reversed_token
    return natural


def extract_url_key(product: str) -> str:
    """Return the StockX url key from a bare key or a stockx.com product URL."""
    value = (product or "").strip()
    if not value:
        raise ClientError("A product url key or stockx.com product URL is required.")
    if "://" not in value:
        return value.strip("/")
    path = urlparse(value).path.strip("/")
    if not path:
        raise ClientError(f"No product url key found in URL {value!r}.")
    return path.rsplit("/", 1)[-1]


def _validate_choice(value: str, allowed: tuple, label: str) -> str:
    if value not in allowed:
        raise ClientError(
            f"Invalid {label} {value!r}. Valid values: {', '.join(allowed)}."
        )
    return value


class StockxClient:
    """Drives a live stockx.com page and calls its own GraphQL catalog API."""

    def __init__(
        self,
        config=None,
        max_retries: int = DEFAULT_REQUESTS_MAX_RETRIES,
        base_delay: float = DEFAULT_REQUESTS_BASE_DELAY,
        max_delay: float = DEFAULT_REQUESTS_MAX_DELAY,
        jitter: float = DEFAULT_REQUESTS_JITTER,
    ):
        self.config = config or get_config()
        # Shared exponential-backoff-with-jitter policy (the same formula every
        # requests-backed CLI here uses). It has no dependency on `requests`, so
        # it applies equally to this in-page fetch's own timing.
        self._retry_policy = RequestsRetryPolicy(
            max_retries=max_retries,
            base_delay=base_delay,
            max_delay=max_delay,
            jitter=jitter,
            retryable_status_codes=DEFAULT_REQUESTS_RETRYABLE_STATUS_CODES,
        )
        self._browser = None

    def _get_browser(self):
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def close(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    @property
    def _home_url(self) -> str:
        return f"{self.config.base_url.rstrip('/')}/"

    def product_url(self, url_key: str) -> str:
        return f"{self.config.base_url.rstrip('/')}/{url_key}"

    def _ready_page(self):
        """Return the session page once StockX's app payload is readable.

        stockx.com walls unknown browsers, and it also finishes writing
        ``__NEXT_DATA__`` shortly after navigation returns, so poll for the
        payload rather than reading once and reporting a false block.
        """
        page = self._get_browser().get_page(self._home_url)
        for attempt in range(_APP_READY_ATTEMPTS):
            if page.evaluate(_APP_VERSION_JS):
                return page
            page.wait_for_timeout(_APP_READY_POLL_MS)
        raise ClientError(
            "StockX did not serve its app payload at "
            f"{self._home_url} after {_APP_READY_ATTEMPTS} checks. stockx.com "
            "walls unknown browsers and rate-limits rapid repeat sessions; wait "
            "a few seconds and retry, or run 'stockx auth test' to inspect the "
            "live session."
        )

    def _app_version(self) -> str:
        """StockX's deployed web-bundle version, from the live page."""
        return self._ready_page().evaluate(_APP_VERSION_JS)

    @cached
    def _persisted_hash(self, operation: str, app_version: str) -> str:
        """Read ``operation``'s current persisted-query hash from StockX's app.

        Cached against ``app_version``, so a StockX deploy naturally produces a
        cache miss and a fresh capture. ``app_version`` is a parameter rather
        than an instance read precisely so it joins the cache key.
        """
        seed_path = self._hash_seed_path(operation)
        page = self._ready_page()
        page.evaluate(_INSTALL_INTERCEPTOR_JS)
        page.evaluate(
            "(path) => { window.next.router.push(path); return true; }", seed_path
        )
        for _ in range(20):
            page.wait_for_timeout(1000)
            hashes = page.evaluate("() => window.__stockxHashes")
            if hashes and operation in hashes:
                return hashes[operation]
        raise ClientError(
            f"StockX did not issue a {operation} request while loading "
            f"{seed_path!r}, so its persisted query hash could not be read. "
            "StockX may have renamed the operation; re-check the page that "
            "fires it."
        )

    def _hash_seed_path(self, operation: str) -> str:
        """Client-side route whose load fires ``operation``."""
        if operation == SEARCH_OPERATION:
            return f"/search?s={HASH_SEED_QUERY}"
        if operation in (PRODUCT_OPERATION, MARKET_OPERATION):
            return f"/{self._seed_url_key()}"
        raise ClientError(f"No persisted-query seed page is known for {operation!r}.")

    @cached
    def _seed_url_key(self) -> str:
        """A live product url key, used only to fire the product operations."""
        products = self.search_products(query=HASH_SEED_QUERY, limit=1)
        if not products:
            raise ClientError(
                f"StockX returned no products for the seed query "
                f"{HASH_SEED_QUERY!r}, so the product page hashes could not be read."
            )
        return products[0]["urlKey"]

    def _retry_after_seconds(self, raw: Optional[str]) -> Optional[float]:
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _graphql(self, operation: str, variables: dict) -> dict:
        """Run the in-page persisted GraphQL POST with exponential-backoff retry."""
        query_hash = self._persisted_hash(operation, self._app_version())
        page = self._ready_page()
        policy = self._retry_policy
        last_exception: Optional[Exception] = None
        last_status = None

        for attempt in range(policy.max_retries + 1):
            try:
                result = page.evaluate(
                    _FETCH_JS,
                    {
                        "path": GRAPHQL_PATH,
                        "operationName": operation,
                        "variables": variables,
                        "hash": query_hash,
                    },
                )
            except Exception as exc:  # browser-harness / network failure
                last_exception = exc
                if attempt < policy.max_retries:
                    time.sleep(policy.calculate_delay(attempt))
                    continue
                raise ClientError(
                    f"StockX {operation} failed after {attempt + 1} attempts: {exc}"
                ) from exc

            status = int(result.get("status") or 0)
            last_status = status
            body = str(result.get("body") or "")
            if status in policy.retryable_status_codes and attempt < policy.max_retries:
                time.sleep(
                    policy.calculate_delay(
                        attempt, self._retry_after_seconds(result.get("retryAfter"))
                    )
                )
                continue
            if status != 200:
                raise ClientError(
                    f"StockX {operation} HTTP {status} "
                    f"{result.get('statusText', '')}: {body[:300]}"
                )
            try:
                payload = json.loads(body)
            except (ValueError, TypeError) as exc:
                raise ClientError(
                    f"StockX {operation} returned a non-JSON body: {exc}"
                ) from exc
            if payload.get("errors"):
                message = "; ".join(str(err.get("message")) for err in payload["errors"])
                raise ClientError(f"StockX {operation} returned errors: {message}")
            return payload["data"]

        raise ClientError(
            f"StockX {operation} failed after retries "
            f"(last status={last_status}): {last_exception}"
        )

    def _build_filters(
        self,
        brand: Optional[List[str]],
        gender: Optional[List[str]],
        category: Optional[List[str]],
        color: Optional[List[str]],
        activity: Optional[List[str]],
        below_retail: bool,
        xpress_ship: bool,
        min_price: Optional[float],
        max_price: Optional[float],
    ) -> List[Dict]:
        filters: List[Dict] = []
        if brand:
            # StockX brand values are slugs (`nike`), not display names; a
            # display name is silently ignored, so normalize case and spacing.
            filters.append(
                {"id": "brand", "selectedValues": [b.strip().lower() for b in brand]}
            )
        if gender:
            filters.append({
                "id": "gender",
                "selectedValues": [
                    _validate_choice(g, GENDER_VALUES, "--gender") for g in gender
                ],
            })
        if category:
            filters.append({
                "id": "category",
                "selectedValues": [
                    _validate_choice(c, CATEGORY_VALUES, "--category") for c in category
                ],
            })
        if color:
            filters.append({
                "id": "color",
                "selectedValues": [
                    _validate_choice(c, COLOR_VALUES, "--color") for c in color
                ],
            })
        if activity:
            filters.append({
                "id": "activity",
                "selectedValues": [a.strip().lower() for a in activity],
            })
        if below_retail:
            filters.append({"id": "below-retail", "selectedValues": ["true"]})
        if xpress_ship:
            filters.append({"id": "xpress-ship", "selectedValues": ["true"]})
        if min_price is not None or max_price is not None:
            if min_price is None or max_price is None:
                raise ClientError(
                    "StockX's price filter is a range: pass both --min-price and "
                    "--max-price, or neither."
                )
            # Verified live: this filter takes two separate values; a single
            # "min-max" string is rejected with HTTP 400.
            filters.append({
                "id": "lowest-ask-range",
                "selectedValues": [str(int(min_price)), str(int(max_price))],
            })
        return filters

    @cached
    def search_products(
        self,
        query: Optional[str] = None,
        limit: int = 40,
        sort_id: str = DEFAULT_SORT,
        brand: Optional[List[str]] = None,
        gender: Optional[List[str]] = None,
        category: Optional[List[str]] = None,
        color: Optional[List[str]] = None,
        activity: Optional[List[str]] = None,
        below_retail: bool = False,
        xpress_ship: bool = False,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
    ) -> List[dict]:
        """Search the StockX catalog, or browse it when ``query`` is None.

        Every filter and the sort are sent to StockX itself (server-side), and
        ``limit`` drives page size plus pagination rather than slicing a
        client-side list. ``sort_id`` is the already-resolved StockX id from
        :func:`resolve_sort`.
        """
        filters = self._build_filters(
            brand, gender, category, color, activity,
            below_retail, xpress_ship, min_price, max_price,
        )
        products: List[dict] = []
        seen = set()
        index = 1

        while len(products) < limit and index <= MAX_PAGES:
            variables = dict(_BROWSE_VARIABLES)
            variables.update({
                "query": query,
                "filters": filters,
                "sort": {"id": sort_id},
                "page": {
                    "index": index,
                    "limit": min(PAGE_SIZE, max(limit - len(products), 1)),
                },
            })
            data = self._graphql(SEARCH_OPERATION, variables)
            edges = data["browse"]["results"]["edges"]
            if not edges:
                break
            for edge in edges:
                node = edge.get("node")
                if not node:
                    continue
                product_id = node.get("id")
                if product_id in seen:
                    continue
                seen.add(product_id)
                products.append(node)
            index += 1

        return normalize_products(products[:limit], self.product_url)

    @cached
    def get_product(self, product: str) -> dict:
        """Get the catalog record for one product by url key or product URL."""
        url_key = extract_url_key(product)
        data = self._graphql(PRODUCT_OPERATION, {"id": url_key, "skipBreadcrumbs": True})
        record = data.get("product")
        if not record:
            raise ClientError(f"StockX returned no product for {url_key!r}.")
        return normalize_product(record, self.product_url)

    @cached
    def get_market(self, product: str) -> dict:
        """Get live market data (asks, bids, sales) for one product."""
        url_key = extract_url_key(product)
        data = self._graphql(
            MARKET_OPERATION,
            {
                "id": url_key,
                "currencyCode": "USD",
                "marketName": "US",
                "viewerContext": "BUYER",
                "includeProcessingFeeForPricing": True,
            },
        )
        record = data.get("product")
        if not record:
            raise ClientError(f"StockX returned no market data for {url_key!r}.")
        return normalize_market(record, self.product_url)


_client: Optional[StockxClient] = None


def get_client() -> StockxClient:
    """Get or create the global StockX client instance."""
    global _client
    if _client is None:
        _client = StockxClient()
    return _client
