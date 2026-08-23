"""America's Thrift Supply Shopify storefront API client.

Uses the public, unauthenticated Shopify storefront JSON endpoints:
  - GET /products.json                       - paginated catalog listing
  - GET /products/{handle}.js                 - single product detail (richest shape:
                                                 includes live per-variant availability
                                                 and prices in cents)
  - GET /collections.json                     - category listing
  - GET /collections/{handle}/products.json   - products scoped to one collection

No API key, login, or browser session is required or supported; the store exposes
these endpoints publicly for any storefront visitor.
"""

import random
import time
from typing import Dict, List, Optional

import requests
from cli_tools_shared.config import get_cache_ttl, is_cache_enabled
from cli_tools_shared.data_cache import cache_dir_for, cached, get_cache_hit
from cli_tools_shared.exceptions import ClientError

from .config import get_config

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 2.0
DEFAULT_MAX_DELAY = 65.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
PAGE_SIZE = 250

# Seconds to wait between two consecutive *live* page requests during a crawl.
# The storefront rate-limits bursts (HTTP 429 `local_rate_limited`), so paging
# is paced explicitly. A single-page request never waits, so this costs nothing
# for the common `--limit <= 250` case.
DEFAULT_PAGE_DELAY = 5.0

# Pace suggested in the rate-limit error when the current pace was not enough.
SUGGESTED_RETRY_PAGE_DELAY = 30.0


class PagedCrawlError(ClientError):
    """A multi-page crawl hit a terminal error, with resume context attached.

    Carries how far the crawl got, whether the completed pages were persisted,
    and how to resume, so a rate-limited full-catalog crawl reports something
    actionable instead of a bare ``HTTP 429: local_rate_limited``.
    """

    def __init__(
        self,
        cause: ClientError,
        endpoint: str,
        resource: str,
        pages_fetched: int,
        items_fetched: int,
        page_delay: float,
        cache_dir,
        cache_enabled: bool,
    ):
        self.cause = cause
        self.endpoint = endpoint
        self.pages_fetched = pages_fetched
        self.items_fetched = items_fetched
        self.page_delay = page_delay

        if cache_enabled:
            persistence = (
                f"Those {pages_fetched} page(s) are cached at {cache_dir} - re-run the same command "
                f"to resume from page {pages_fetched + 1} without re-requesting them "
                f"(cache TTL {get_cache_ttl()}s)."
            )
        else:
            persistence = (
                "Response caching is disabled (--no-cache / CACHE_ENABLED=false), so no page was "
                "persisted and a re-run restarts at page 1. Drop --no-cache to make crawls resumable."
            )

        super().__init__(
            f"{cause}\n"
            f"Crawl of {endpoint} stopped after {pages_fetched} page(s) yielding {items_fetched} {resource}.\n"
            f"{persistence}\n"
            f"Retry with a slower pace, e.g. --page-delay {SUGGESTED_RETRY_PAGE_DELAY:g} "
            f"(current: {page_delay:g}s). Run 'americasthriftsupply cache clear' to discard cached "
            f"pages and start over."
        )


def _variant_prices(variants: List[dict]) -> List[float]:
    return [float(v["price"]) for v in variants if v.get("price") not in (None, "")]


def normalize_product(raw: dict, base_url: str) -> dict:
    """Map a /products.json (or /collections/{handle}/products.json) product to
    the public CLI record shape. Every field from the API response is preserved;
    the fields below are added for convenience (stable URL, USD-normalized price,
    aggregate availability)."""
    variants = raw.get("variants", [])
    images = raw.get("images", [])
    prices = _variant_prices(variants)
    availability_reported = bool(variants) and "available" in variants[0]

    return {
        **raw,
        "url": f"{base_url}/products/{raw['handle']}",
        "price_usd": prices[0] if prices else None,
        "price_min_usd": min(prices) if prices else None,
        "price_max_usd": max(prices) if prices else None,
        "available": (any(v.get("available") for v in variants) if availability_reported else None),
        "variant_count": len(variants),
        "image_count": len(images),
        "image_urls": [image.get("src") for image in images if image.get("src")],
    }


def normalize_product_detail(raw: dict, base_url: str) -> dict:
    """Map a /products/{handle}.js response to the public CLI record shape.

    This endpoint reports prices in cents and includes live per-variant
    ``available`` flags (unlike the legacy /products/{handle}.json endpoint,
    which omits availability entirely)."""
    price_cents = raw.get("price")
    compare_at_price_cents = raw.get("compare_at_price")

    return {
        **raw,
        "url": f"{base_url}/products/{raw['handle']}",
        "price_usd": (price_cents / 100) if price_cents is not None else None,
        "compare_at_price_usd": (compare_at_price_cents / 100) if compare_at_price_cents is not None else None,
        "image_urls": [
            image if image.startswith("http") else f"https:{image}"
            for image in raw.get("images", [])
        ],
        "variant_count": len(raw.get("variants", [])),
    }


def normalize_collection(raw: dict, base_url: str) -> dict:
    """Map a /collections.json collection to the public CLI record shape."""
    return {
        **raw,
        "url": f"{base_url}/collections/{raw['handle']}",
    }


class AmericasthriftsupplyClient:
    """Client for the America's Thrift Supply public Shopify storefront JSON API."""

    def __init__(
        self,
        config=None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = config or get_config()
        self.base_url = self.config.base_url
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.headers = {"Accept": "application/json"}

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_delay)
        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        return min(delay + random.uniform(-jitter_range, jitter_range), self.max_delay)

    def _is_retryable(self, response: Optional[requests.Response], exception: Optional[Exception]) -> bool:
        if exception is not None:
            return isinstance(
                exception,
                (
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.ChunkedEncodingError,
                ),
            )
        if response is not None:
            return response.status_code in RETRYABLE_STATUS_CODES
        return False

    def _get_retry_after(self, response: requests.Response) -> Optional[float]:
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def _extract_error_detail(self, response: requests.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return response.text[:500]
        if isinstance(body, dict) and "errors" in body:
            return str(body["errors"])
        return str(body)[:500]

    def _request_json(self, method: str, url: str, params: Optional[Dict] = None) -> Dict:
        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None
        max_attempts = self.max_retries + 1

        for attempt in range(max_attempts):
            try:
                response = requests.request(method, url, headers=self.headers, params=params, timeout=30)
                last_response = response
                if self._is_retryable(response, None) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt, self._get_retry_after(response)))
                    continue
                break
            except requests.exceptions.RequestException as exc:
                last_exception = exc
                if self._is_retryable(None, exc) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt))
                    continue
                break

        if last_exception is not None and last_response is None:
            raise ClientError(f"Request failed after {attempt + 1} attempts: {last_exception}")
        if last_response is None:
            raise ClientError("Request failed: no response received")
        if not last_response.ok:
            raise ClientError(f"HTTP {last_response.status_code}: {self._extract_error_detail(last_response)}")
        return last_response.json()

    def _make_request(self, method: str, endpoint: str, params: Optional[Dict] = None) -> Dict:
        return self._request_json(method, f"{self.base_url}{endpoint}", params=params)

    @cached
    def _fetch_page(self, endpoint: str, page: int) -> dict:
        """Fetch one page of a Shopify listing endpoint.

        This is the cache unit for every crawl: each page is written to the
        response cache as soon as it arrives, so a crawl that dies partway
        through (rate limit, network) leaves its completed pages on disk and the
        next run resumes at the first uncached page. The page size is fixed at
        ``PAGE_SIZE`` so the cache key depends only on the endpoint and the page
        number, making a page reusable across runs with different ``--limit``.
        """
        return self._make_request("GET", endpoint, params={"limit": PAGE_SIZE, "page": page})

    def _paginate(self, endpoint: str, key: str, resource: str, limit: int, page_delay: float) -> List[dict]:
        """Page through a Shopify listing endpoint until `limit` items are
        collected or the store has no more pages.

        `page_delay` seconds are slept between consecutive *live* requests; a
        page served from cache costs no request and therefore no wait.
        """
        items: List[dict] = []
        page = 1
        pages_fetched = 0
        previous_page_was_live = False

        while len(items) < limit:
            if previous_page_was_live and page_delay > 0:
                time.sleep(page_delay)
            try:
                response = self._fetch_page(endpoint, page)
            except ClientError as exc:
                raise PagedCrawlError(
                    cause=exc,
                    endpoint=endpoint,
                    resource=resource,
                    pages_fetched=pages_fetched,
                    items_fetched=len(items),
                    page_delay=page_delay,
                    cache_dir=cache_dir_for(self),
                    cache_enabled=is_cache_enabled(),
                ) from exc
            previous_page_was_live = get_cache_hit() is False
            if key not in response:
                raise ClientError(f"Unexpected response from {endpoint}: missing '{key}'")

            batch = response[key]
            pages_fetched += 1
            if not batch:
                break
            items.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
            page += 1
        return items[:limit]

    def list_products(
        self,
        limit: int = 100,
        collection: Optional[str] = None,
        page_delay: float = DEFAULT_PAGE_DELAY,
    ) -> List[dict]:
        """List products from the full catalog, or from one collection when
        `collection` (a collection handle, e.g. 'mystery-box') is given."""
        endpoint = f"/collections/{collection}/products.json" if collection else "/products.json"
        raw_products = self._paginate(endpoint, "products", "products", limit, page_delay)
        return [normalize_product(product, self.base_url) for product in raw_products]

    @cached
    def get_product(self, handle: str) -> dict:
        """Get full detail (including live availability) for one product by handle."""
        raw = self._request_json("GET", f"{self.base_url}/products/{handle}.js")
        return normalize_product_detail(raw, self.base_url)

    def list_collections(self, limit: int = 100, page_delay: float = DEFAULT_PAGE_DELAY) -> List[dict]:
        """List storefront collections (categories)."""
        raw = self._paginate("/collections.json", "collections", "collections", limit, page_delay)
        return [normalize_collection(collection, self.base_url) for collection in raw]

    @cached
    def get_collection(self, handle: str) -> dict:
        """Get detail for one collection by handle."""
        response = self._request_json("GET", f"{self.base_url}/collections/{handle}.json")
        return normalize_collection(response["collection"], self.base_url)


_client: Optional[AmericasthriftsupplyClient] = None


def get_client() -> AmericasthriftsupplyClient:
    """Get or create the global Americasthriftsupply client instance."""
    global _client
    if _client is None:
        _client = AmericasthriftsupplyClient()
    return _client
