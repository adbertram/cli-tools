"""Clipster public campaign catalog client."""

import random
import time
from typing import List, Optional

import requests
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from . import __version__
from .config import get_config

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

CAMPAIGNS_ENDPOINT = "/campaigns/public"
PAGE_SIZE = 100
REQUEST_TIMEOUT = 30
CAMPAIGN_WEB_URL = "https://www.clipster.gg/discover?openedCampaignId=%s"
# The API answers Python's default User-Agent with HTTP 403 (measured 2026-10-14).
USER_AGENT = f"clipster-cli/{__version__}"
CATALOG_CACHE_TTL = 300


def normalize_campaign(raw: dict) -> dict:
    """Return the API row unchanged plus the campaign's web page URL."""
    if not isinstance(raw, dict) or "id" not in raw:
        raise ClientError("Clipster campaign row has no id")
    return {**raw, "web_url": CAMPAIGN_WEB_URL % raw["id"]}


class ClipsterClient:
    """Client for Clipster's public, unauthenticated campaign catalog."""

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
        self.headers = {"Accept": "application/json", "User-Agent": USER_AGENT}

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
        return response is not None and response.status_code in RETRYABLE_STATUS_CODES

    def _get_retry_after(self, response: requests.Response) -> Optional[float]:
        try:
            return float(response.headers["Retry-After"])
        except (KeyError, ValueError):
            return None

    def _get_json(self, endpoint: str, params: dict) -> dict:
        """GET one JSON document with exponential-backoff retry."""
        url = f"{self.base_url}{endpoint}"
        response: Optional[requests.Response] = None
        error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            response, error = None, None
            try:
                response = requests.get(url, headers=self.headers, params=params, timeout=REQUEST_TIMEOUT)
            except requests.exceptions.RequestException as exc:
                error = exc
            if attempt < self.max_retries and self._is_retryable(response, error):
                retry_after = self._get_retry_after(response) if response is not None else None
                time.sleep(self._calculate_retry_delay(attempt, retry_after))
                continue
            break

        if response is None:
            raise ClientError(f"Request failed after {attempt + 1} attempts: {error}")
        if not response.ok:
            raise ClientError(f"HTTP {response.status_code}: {response.text[:500]}")
        try:
            return response.json()
        except ValueError as exc:
            raise ClientError(f"Clipster returned a non-JSON response: {exc}") from exc

    def _read_campaigns(self, limit: Optional[int]) -> List[dict]:
        """Read catalog pages until `limit` rows are collected or the last page is read."""
        if limit is not None and limit < 1:
            raise ClientError("--limit must be at least 1")
        page_size = PAGE_SIZE if limit is None else min(limit, PAGE_SIZE)
        rows: List[dict] = []
        page, total_pages = 1, 1
        while page <= total_pages and (limit is None or len(rows) < limit):
            document = self._get_json(CAMPAIGNS_ENDPOINT, {"page": page, "limit": page_size})
            found = ((document or {}).get("data") or {}).get("campaigns") if isinstance(document, dict) else None
            if not isinstance(found, list):
                raise ClientError("Clipster campaign list did not return a list")
            rows += found
            try:
                total_pages = int(((document.get("metadata") or {}).get("pagination") or {}).get("total_pages") or 0)
            except (TypeError, ValueError) as exc:
                raise ClientError(f"Clipster pagination total_pages is not a number: {exc}") from exc
            page += 1
        return rows if limit is None else rows[:limit]

    @cached(ttl=CATALOG_CACHE_TTL)
    def list_campaigns(self, limit: Optional[int] = PAGE_SIZE) -> List[dict]:
        return [normalize_campaign(row) for row in self._read_campaigns(limit)]

    def get_campaign(self, campaign_id: str) -> dict:
        """Find one campaign by id; the catalog has no verified detail route."""
        for row in self.list_campaigns(limit=None):
            if str(row["id"]) == campaign_id:
                return row
        raise ClientError(f"Campaign not found: {campaign_id}")


_client: Optional[ClipsterClient] = None


def get_client() -> ClipsterClient:
    """Get or create the global Clipster client instance."""
    global _client
    if _client is None:
        _client = ClipsterClient()
    return _client
