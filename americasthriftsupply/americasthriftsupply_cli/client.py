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
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .config import get_config

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 2.0
DEFAULT_MAX_DELAY = 65.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_PAGE_SIZE = 250


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

    def _paginate_products(self, endpoint: str, limit: int) -> List[dict]:
        """Page through a Shopify products.json-shaped endpoint until `limit`
        products are collected or the store has no more pages."""
        products: List[dict] = []
        page = 1
        while len(products) < limit:
            page_size = min(MAX_PAGE_SIZE, limit - len(products))
            response = self._make_request(method="GET", endpoint=endpoint, params={"limit": page_size, "page": page})
            batch = response.get("products", [])
            if not batch:
                break
            products.extend(batch)
            if len(batch) < page_size:
                break
            page += 1
        return products[:limit]

    @cached
    def list_products(self, limit: int = 100, collection: Optional[str] = None) -> List[dict]:
        """List products from the full catalog, or from one collection when
        `collection` (a collection handle, e.g. 'mystery-box') is given."""
        endpoint = f"/collections/{collection}/products.json" if collection else "/products.json"
        raw_products = self._paginate_products(endpoint, limit)
        return [normalize_product(product, self.base_url) for product in raw_products]

    @cached
    def get_product(self, handle: str) -> dict:
        """Get full detail (including live availability) for one product by handle."""
        raw = self._request_json("GET", f"{self.base_url}/products/{handle}.js")
        return normalize_product_detail(raw, self.base_url)

    @cached
    def list_collections(self, limit: int = 100) -> List[dict]:
        """List storefront collections (categories)."""
        collections: List[dict] = []
        page = 1
        while len(collections) < limit:
            page_size = min(MAX_PAGE_SIZE, limit - len(collections))
            response = self._make_request("GET", "/collections.json", params={"limit": page_size, "page": page})
            batch = response.get("collections", [])
            if not batch:
                break
            collections.extend(batch)
            if len(batch) < page_size:
                break
            page += 1
        return [normalize_collection(c, self.base_url) for c in collections[:limit]]

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
