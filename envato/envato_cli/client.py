"""Envato Market API client."""

import random
import time
from typing import Dict, List, Optional

import requests
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError, CredentialError

from .config import get_config

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
REQUEST_TIMEOUT = 30
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

SEARCH_PATH = "/v1/discovery/search/search/item"
ITEM_PATH = "/v3/market/catalog/item"
USERNAME_PATH = "/v1/market/private/user/username.json"

# --sort value -> (Envato sort_by, natural sort_direction). --desc flips the direction.
SORT_MAP = {
    "newest": ("date", "desc"),
    "updated": ("updated", "desc"),
    "price": ("price", "asc"),
    "sales": ("sales", "asc"),
    "rating": ("rating", "asc"),
    "relevance": ("relevance", None),
}


def resolve_sort(sort: str, desc: bool) -> Dict[str, str]:
    """Return the Envato sort params for a --sort/--desc pair, failing on unknown values."""
    key = sort.lower()
    if key not in SORT_MAP:
        raise ClientError(f"Invalid --sort '{sort}'. Valid values: {', '.join(SORT_MAP)}")
    sort_by, direction = SORT_MAP[key]
    if direction is None:
        if desc:
            raise ClientError(f"--desc cannot be used with --sort {key}")
        return {"sort_by": sort_by}
    if desc:
        direction = "asc" if direction == "desc" else "desc"
    return {"sort_by": sort_by, "sort_direction": direction}


def resolve_site(site: str) -> str:
    """Map a short site name (codecanyon) to its Envato domain (codecanyon.net)."""
    site = site.strip().lower()
    return site if "." in site else f"{site}.net"


def _record(raw: dict, rating: float, rating_count: int) -> dict:
    return {
        "id": raw["id"],
        "title": raw["name"],
        "url": raw["url"],
        "price": raw["price_cents"] / 100,
        "number_of_sales": raw["number_of_sales"],
        "rating": rating,
        "rating_count": rating_count,
        "published_at": raw["published_at"],
        "updated_at": raw["updated_at"],
        "site": raw["site"],
    }


def normalize_search_match(raw: dict) -> dict:
    """Search matches carry rating as {"rating": float, "count": int}."""
    return _record(raw, raw["rating"]["rating"], raw["rating"]["count"])


def normalize_item(raw: dict) -> dict:
    """Catalog items carry rating as a number with a separate rating_count."""
    return _record(raw, raw["rating"], raw["rating_count"])


class EnvatoClient:
    """Client for the Envato Market API."""

    def __init__(
        self,
        config=None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = config or get_config()
        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise CredentialError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'envato auth login' to authenticate."
            )
        self.base_url = self.config.base_url
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.config.personal_access_token}",
        }

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_delay)
        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        return min(delay + random.uniform(-jitter_range, jitter_range), self.max_delay)

    def _get_retry_after(self, response: requests.Response) -> Optional[float]:
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def _extract_error_detail(self, response: requests.Response) -> str:
        """Envato errors are {"error": "<msg>"} or {"error": <code>, "description": "<msg>"}."""
        try:
            body = response.json()
        except ValueError:
            return response.text[:500]
        if isinstance(body, dict):
            detail = body.get("description") or body.get("error")
            if detail:
                return str(detail)
        return str(body)[:500]

    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        url = f"{self.base_url}{endpoint}"
        for attempt in range(self.max_retries + 1):
            last_attempt = attempt == self.max_retries
            try:
                response = requests.get(url, headers=self.headers, params=params, timeout=REQUEST_TIMEOUT)
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ) as exc:
                if last_attempt:
                    raise ClientError(f"Request failed after {attempt + 1} attempts: {exc}") from exc
                time.sleep(self._calculate_retry_delay(attempt))
                continue
            except requests.exceptions.RequestException as exc:
                raise ClientError(f"Request failed: {exc}") from exc
            if response.status_code in RETRYABLE_STATUS_CODES and not last_attempt:
                time.sleep(self._calculate_retry_delay(attempt, self._get_retry_after(response)))
                continue
            break

        if response.status_code in (401, 403):
            raise CredentialError(
                f"HTTP {response.status_code}: {self._extract_error_detail(response)}. "
                "Run 'envato auth login --force' with a valid personal token."
            )
        if not response.ok:
            raise ClientError(f"HTTP {response.status_code}: {self._extract_error_detail(response)}")
        try:
            return response.json()
        except ValueError as exc:
            raise ClientError(f"Envato returned non-JSON response (HTTP {response.status_code})") from exc

    def get_username(self) -> str:
        return self._get(USERNAME_PATH)["username"]

    @cached
    def search_items(
        self,
        term: str,
        site: str,
        limit: int,
        page: int,
        sort_params: Dict[str, str],
    ) -> List[dict]:
        params = {"term": term, "site": site, "page_size": limit, "page": page, **sort_params}
        return [normalize_search_match(m) for m in self._get(SEARCH_PATH, params)["matches"]]

    @cached
    def get_item(self, item_id: str) -> dict:
        return normalize_item(self._get(ITEM_PATH, {"id": item_id}))


_client: Optional[EnvatoClient] = None


def get_client() -> EnvatoClient:
    """Get or create the global Envato client instance."""
    global _client
    if _client is None:
        _client = EnvatoClient()
    return _client
