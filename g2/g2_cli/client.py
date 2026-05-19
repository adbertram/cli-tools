"""G2 API client."""

import fnmatch
import random
import time
from typing import Any, Dict, Iterable, List, Optional

import requests
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .config import get_config

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
JSON_CONTENT_TYPE = "application/json"
PRODUCTS_ENDPOINT = "/api/v2/products"
DATA_SOLUTIONS_REVIEWS_ENDPOINT = "/api/v2/data_solutions/reviews"


def _attributes(resource: dict) -> dict:
    attributes = resource.get("attributes")
    if not isinstance(attributes, dict):
        raise ClientError("Expected JSON:API resource attributes to be an object.")
    return attributes


def normalize_product(resource: dict) -> dict:
    """Normalize a G2 product JSON:API resource."""
    attrs = _attributes(resource)
    return {
        "id": resource["id"],
        "name": attrs.get("name"),
        "slug": attrs.get("slug"),
        "product_type": attrs.get("type"),
        "domain": attrs.get("domain"),
        "detail_description": attrs.get("detail_description"),
        "g2_url": attrs.get("g2_url"),
        "image_url": attrs.get("image_url"),
        "pricing_tiers": attrs.get("pricing_tiers"),
        "review_count": attrs.get("review_count"),
        "star_rating": attrs.get("star_rating"),
        "public_detail_url": attrs.get("public_detail_url"),
        "write_review_url": attrs.get("write_review_url"),
    }


def normalize_review(resource: dict, *, product_slug: Optional[str] = None) -> dict:
    """Normalize a Data Solutions review into the CLI review record shape."""
    attrs = _attributes(resource)
    resolved_product_slug = product_slug or attrs.get("product_id")
    return {
        "id": attrs.get("survey_response_id") or resource["id"],
        "product_name": attrs.get("product_name"),
        "product_slug": resolved_product_slug,
        "star_rating": attrs.get("star_rating"),
        "title": attrs.get("title"),
        "dislike_text": attrs.get("hate"),
        "recommendation_text": attrs.get("recommendations"),
        "benefits_text": attrs.get("benefits"),
        "review_source": attrs.get("source"),
        "submitted_at": attrs.get("submitted_at"),
        "public_url": attrs.get("url"),
    }


class G2Client:
    """Client for interacting with the G2 API."""

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = get_config()
        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'g2 auth login' to authenticate."
            )
        self.base_url = self.config.base_url.rstrip("/")
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self._update_headers()

    def _update_headers(self) -> None:
        token = self.config.personal_access_token
        if not token:
            raise ClientError("Missing personal access token. Run 'g2 auth login' to authenticate.")
        self.headers = {
            "Accept": JSON_CONTENT_TYPE,
            "Content-Type": JSON_CONTENT_TYPE,
            "Authorization": f"Bearer {token}",
        }

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
        if isinstance(body, dict) and isinstance(body.get("errors"), list) and body["errors"]:
            parts = []
            for error in body["errors"]:
                if not isinstance(error, dict):
                    continue
                part = " ".join(
                    str(value)
                    for value in (error.get("status"), error.get("title"), error.get("detail"))
                    if value
                )
                if part:
                    parts.append(part)
            if parts:
                return " | ".join(parts)
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            error = body["error"]
            return error.get("message") or error.get("code") or str(error)
        if isinstance(body, dict) and "message" in body:
            return str(body["message"])
        return str(body)[:500]

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        retry: bool = True,
    ) -> Dict[str, Any]:
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            url = endpoint
        else:
            if not endpoint.startswith("/"):
                raise ClientError("G2 API endpoints must start with '/'.")
            url = f"{self.base_url}{endpoint}"
        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None
        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                response = requests.request(
                    method,
                    url,
                    headers=self.headers,
                    json=data,
                    params=params,
                    timeout=30,
                )
                last_response = response
                if retry and self._is_retryable(response, None) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt, self._get_retry_after(response)))
                    continue
                break
            except requests.exceptions.RequestException as exc:
                last_exception = exc
                if retry and self._is_retryable(None, exc) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt))
                    continue
                break

        if last_exception is not None and last_response is None:
            raise ClientError(f"Request failed after {attempt + 1} attempts: {last_exception}")
        if last_response is None:
            raise ClientError("Request failed: no response received")
        if not last_response.ok:
            raise ClientError(f"HTTP {last_response.status_code}: {self._extract_error_detail(last_response)}")
        if last_response.status_code == 204:
            return {}
        return last_response.json()

    @cached
    def list_products(self, limit: int = 100) -> List[dict]:
        return [normalize_product(resource) for resource in self._collect_resources(PRODUCTS_ENDPOINT, limit=limit)]

    @cached
    def get_product(self, slug: str) -> dict:
        body = self._make_request("GET", f"{PRODUCTS_ENDPOINT}/{slug}")
        return normalize_product(self._expect_resource(body, "data"))

    @cached
    def search_products(self, query: str, limit: int = 100) -> List[dict]:
        body = self._make_request(
            "GET",
            PRODUCTS_ENDPOINT,
            params={
                "filter[query]": query,
                "page[size]": min(max(limit, 1), 100),
            },
        )
        return [normalize_product(resource) for resource in self._expect_collection(body)[:limit]]

    @cached
    def list_reviews(self, product_slug: str, *, stars: Optional[List[int]] = None, limit: int = 100) -> List[dict]:
        reviews = [
            normalize_review(resource, product_slug=product_slug)
            for resource in self._collect_resources(
                DATA_SOLUTIONS_REVIEWS_ENDPOINT,
                limit=limit,
                params={"filter[product_id][]": product_slug},
            )
        ]
        return self._filter_stars(reviews, stars)

    @cached
    def get_review(self, review_id: str) -> dict:
        for resource in self._iter_resources(DATA_SOLUTIONS_REVIEWS_ENDPOINT):
            if self._matches_review_identifier(resource, review_id):
                return normalize_review(resource)
        raise ClientError(
            f"No accessible G2 review found matching '{review_id}'. "
            "The Data Solutions reviews endpoint only returns reviews available to your account."
        )

    @cached
    def search_reviews(
        self,
        product_slug: str,
        query: str,
        *,
        stars: Optional[List[int]] = None,
        limit: int = 100,
    ) -> List[dict]:
        pattern = self._search_pattern(query)
        matches: List[dict] = []
        for review in self.list_reviews(product_slug, stars=stars, limit=limit):
            if self._matches_query(review, pattern):
                matches.append(review)
                if len(matches) >= limit:
                    break
        return matches

    def _matches_review_identifier(self, resource: dict, review_id: str) -> bool:
        attrs = _attributes(resource)
        candidates = {str(resource["id"])}
        for value in (attrs.get("survey_response_id"), attrs.get("slug")):
            if value is not None:
                candidates.add(str(value))
        return review_id in candidates

    def _resolve_product_resource(self, slug: str) -> dict:
        body = self._make_request(
            "GET",
            PRODUCTS_ENDPOINT,
            params={"filter[slug][]": slug, "page[size]": 1},
        )
        resources = self._expect_collection(body)
        if not resources:
            raise ClientError(f"No G2 product found for slug '{slug}'.")
        return resources[0]

    def _expect_collection(self, body: Dict[str, Any]) -> List[dict]:
        data = body.get("data")
        if not isinstance(data, list):
            raise ClientError("Expected JSON:API response 'data' to be a list.")
        return data

    def _expect_resource(self, body: Dict[str, Any], key: str) -> dict:
        resource = body.get(key)
        if not isinstance(resource, dict):
            raise ClientError(f"Expected JSON:API response '{key}' to be an object.")
        return resource

    def _iter_resources(
        self,
        endpoint: str,
        *,
        page_size: int = 100,
        params: Optional[Dict[str, Any]] = None,
    ) -> Iterable[dict]:
        next_endpoint: Optional[str] = endpoint
        request_params: Optional[Dict[str, Any]] = {"page[size]": page_size}
        if params:
            request_params.update(params)
        while next_endpoint is not None:
            body = self._make_request("GET", next_endpoint, params=request_params)
            for resource in self._expect_collection(body):
                yield resource
            links = body.get("links") or {}
            if not isinstance(links, dict):
                raise ClientError("Expected JSON:API response links to be an object.")
            next_link = links.get("next")
            next_endpoint = str(next_link) if next_link else None
            request_params = None

    def _collect_resources(
        self,
        endpoint: str,
        *,
        limit: int,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[dict]:
        resources: List[dict] = []
        for resource in self._iter_resources(
            endpoint,
            page_size=min(max(limit, 1), 100),
            params=params,
        ):
            resources.append(resource)
            if len(resources) >= limit:
                break
        return resources

    def _matches_query(self, row: dict, pattern: str) -> bool:
        for value in row.values():
            if value is None:
                continue
            if fnmatch.fnmatch(str(value).lower(), pattern):
                return True
        return False

    def _search_pattern(self, query: str) -> str:
        pattern = query.lower()
        if "*" not in pattern:
            pattern = f"*{pattern}*"
        return pattern

    def _filter_stars(self, reviews: List[dict], stars: Optional[List[int]]) -> List[dict]:
        if not stars:
            return reviews
        allowed = {float(star) for star in stars}
        return [review for review in reviews if float(review["star_rating"]) in allowed]


_client = None


def get_client() -> G2Client:
    global _client
    if _client is None:
        _client = G2Client()
    return _client
