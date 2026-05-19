"""DEV Community API client."""

from __future__ import annotations

import random
import time
from typing import Any, Dict, List, Optional

import requests
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from . import __version__
from .config import API_ACCEPT_HEADER, get_config

API_ACCEPT_HEADER = "application/vnd.forem.api-v1+json"
DEFAULT_USER_AGENT = f"dev_to-cli/{__version__}"
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
MAX_PER_PAGE = 1000
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _normalize_tag_list(raw: dict) -> List[str]:
    """Return tags as a normalized list of strings."""
    tag_list = raw.get("tag_list")
    if isinstance(tag_list, list):
        return [str(tag) for tag in tag_list]
    if isinstance(tag_list, str):
        if not tag_list.strip():
            return []
        return [tag.strip() for tag in tag_list.split(",") if tag.strip()]

    tags = raw.get("tags")
    if isinstance(tags, list):
        return [str(tag) for tag in tags]
    if isinstance(tags, str):
        if not tags.strip():
            return []
        return [tag.strip() for tag in tags.split(",") if tag.strip()]
    if tags is None:
        return []

    raise ClientError("Expected article tags to be a string, list, or null.")


def normalize_article(raw: dict) -> dict:
    """Map one DEV article payload to the public CLI record shape."""
    if not isinstance(raw, dict):
        raise ClientError("Expected article payload to be an object.")

    user = raw.get("user")
    organization = raw.get("organization")
    tag_list = _normalize_tag_list(raw)

    return {
        "id": raw["id"],
        "type_of": raw.get("type_of"),
        "title": raw["title"],
        "description": raw.get("description"),
        "published": raw.get("published", raw.get("published_at") is not None),
        "slug": raw.get("slug"),
        "path": raw.get("path"),
        "url": raw.get("url"),
        "canonical_url": raw.get("canonical_url"),
        "cover_image": raw.get("cover_image"),
        "published_at": raw.get("published_at"),
        "published_timestamp": raw.get("published_timestamp"),
        "created_at": raw.get("created_at"),
        "edited_at": raw.get("edited_at"),
        "reading_time_minutes": raw.get("reading_time_minutes"),
        "tag_list": tag_list,
        "body_markdown": raw.get("body_markdown"),
        "user": {
            "name": user.get("name"),
            "username": user.get("username"),
        } if isinstance(user, dict) else None,
        "organization": {
            "name": organization.get("name"),
            "username": organization.get("username"),
        } if isinstance(organization, dict) else None,
    }


def build_create_payload(
    *,
    title: str,
    body_markdown: str,
    published: bool,
    tags: Optional[str],
    canonical_url: Optional[str],
    description: Optional[str],
    series: Optional[str],
    main_image: Optional[str],
) -> Dict[str, Dict[str, Any]]:
    """Build the official article-create request payload."""
    article: Dict[str, Any] = {
        "title": title,
        "body_markdown": body_markdown,
        "published": published,
    }
    if tags is not None:
        tag_names = [tag.strip() for tag in tags.split(",") if tag.strip()]
        if not tag_names:
            raise ClientError("Expected at least one non-empty tag in --tags.")
        article["tags"] = ", ".join(tag_names)
    if canonical_url is not None:
        article["canonical_url"] = canonical_url
    if description is not None:
        article["description"] = description
    if series is not None:
        article["series"] = series
    if main_image is not None:
        article["main_image"] = main_image
    return {"article": article}


class DevToClient:
    """Client for interacting with the DEV Community article API."""

    def __init__(
        self,
        config=None,
        session: Optional[requests.Session] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = config if config is not None else get_config()
        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'dev_to auth login' to authenticate."
            )

        self.base_url = self.config.base_url.rstrip("/")
        self.session = session if session is not None else requests.Session()
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Accept": API_ACCEPT_HEADER,
            "Content-Type": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
            "api-key": self.config.api_key,
        }

    def _url(self, endpoint: str) -> str:
        return f"{self.base_url}{endpoint}"

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_delay)
        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        return min(delay + random.uniform(-jitter_range, jitter_range), self.max_delay)

    def _is_retryable(
        self,
        response: Optional[requests.Response] = None,
        exception: Optional[Exception] = None,
    ) -> bool:
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
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def _error_detail(self, response: requests.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            return response.text
        if isinstance(data, dict):
            if "error" in data:
                return str(data["error"])
            if "message" in data:
                return str(data["message"])
        return str(data)

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        retry: bool = True,
    ) -> Any:
        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None
        max_attempts = self.max_retries + 1 if retry else 1

        for attempt in range(max_attempts):
            try:
                last_response = self.session.request(
                    method,
                    self._url(endpoint),
                    headers=self.headers,
                    json=data,
                    params=params,
                    timeout=30,
                )
                if retry and self._is_retryable(response=last_response) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt, self._get_retry_after(last_response)))
                    continue
                break
            except requests.exceptions.RequestException as exc:
                last_exception = exc
                if retry and self._is_retryable(exception=exc) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt))
                    continue
                break

        if last_response is None:
            raise ClientError(f"Request failed after {max_attempts} attempts: {last_exception}")

        if not 200 <= last_response.status_code < 300:
            raise ClientError(f"HTTP {last_response.status_code}: {self._error_detail(last_response)}")

        if last_response.status_code == 204:
            return {}

        return last_response.json()

    @cached
    def list_posts(self, limit: int = 100) -> List[dict]:
        """List the authenticated user's articles."""
        if limit < 1:
            raise ClientError("Expected --limit to be greater than 0.")

        posts: List[dict] = []
        page = 1

        while len(posts) < limit:
            per_page = min(limit - len(posts), MAX_PER_PAGE)
            page_items = self._make_request(
                "GET",
                "/articles/me/all",
                params={"page": page, "per_page": per_page},
            )
            if not isinstance(page_items, list):
                raise ClientError("Expected article list response to be an array.")
            posts.extend(normalize_article(item) for item in page_items)
            if len(page_items) < per_page:
                break
            page += 1

        return posts[:limit]

    @cached
    def get_post(self, post_id: int) -> dict:
        """Get one authenticated user's article by ID."""
        if post_id < 1:
            raise ClientError("Expected post_id to be greater than 0.")

        page = 1
        while True:
            page_items = self._make_request(
                "GET",
                "/articles/me/all",
                params={"page": page, "per_page": MAX_PER_PAGE},
            )
            if not isinstance(page_items, list):
                raise ClientError("Expected article list response to be an array.")
            for item in page_items:
                if not isinstance(item, dict):
                    raise ClientError("Expected article list item to be an object.")
                if item.get("id") == post_id:
                    return normalize_article(item)
            if len(page_items) < MAX_PER_PAGE:
                break
            page += 1

        raise ClientError(f"Article {post_id} was not found in authenticated user's articles.")

    def create_post(
        self,
        *,
        title: str,
        body_markdown: str,
        published: bool = False,
        tags: Optional[str] = None,
        canonical_url: Optional[str] = None,
        description: Optional[str] = None,
        series: Optional[str] = None,
        main_image: Optional[str] = None,
    ) -> dict:
        """Create a new DEV article."""
        payload = build_create_payload(
            title=title,
            body_markdown=body_markdown,
            published=published,
            tags=tags,
            canonical_url=canonical_url,
            description=description,
            series=series,
            main_image=main_image,
        )
        return normalize_article(self._make_request("POST", "/articles", data=payload))

    def remove_post(self, post_id: int) -> dict:
        """Unpublish one DEV article through the documented Forem endpoint."""
        if post_id < 1:
            raise ClientError("Expected post_id to be greater than 0.")

        article = self.get_post(post_id)
        if article["published"] is False:
            return article

        self._make_request("PUT", f"/articles/{post_id}/unpublish", retry=False)
        return self.get_post(post_id)


_client: Optional[DevToClient] = None


def get_client() -> DevToClient:
    """Get or create the global DEV client instance."""
    global _client
    if _client is None:
        _client = DevToClient()
    return _client
