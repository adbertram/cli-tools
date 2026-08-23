"""Pluralsight public-catalog search client (Cludo site-search API).

The catalog search endpoint is public: it authenticates with the static site
key Pluralsight publishes inside its own web pages (base64 of
``customerId:engineId:SearchKey``). It is not a user credential.
"""

import random
import time
from datetime import datetime
from typing import Dict, List, Optional

import requests
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .config import get_config

SITE_AUTHORIZATION = "SiteKey MTAwMDA4NDc6MTAwMDEyNzg6U2VhcmNoS2V5"
REFERER = "https://www.pluralsight.com/"

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Content-type facet tokens accepted by --category, mapped to Cludo
# ``categories`` facet values. ``all`` removes the facet filter entirely.
CATEGORY_MAP = {
    "course": ["course"],
    "path": ["skill"],
    "skill": ["skill"],
    "labs": ["labs"],
    "certificate": ["certificate"],
}
# Mirrors the defaults pluralsight.com/browse sends for its own results grid.
DEFAULT_CATEGORIES = ["course", "labs", "certificate", "skill"]

REQUEST_FIELDS = [
    "Title",
    "Url",
    "categories",
    "Category",
    "course-category",
    "course-catalog",
    "roles",
    "authors",
    "rating",
    "rating-count",
    "duration",
    "Skill Levels",
    "publish-date",
    "updated-date",
    "prodId",
    "numberOfLabs",
    "numberOfCourses",
    "retired",
]

SORT_MAP = {
    "relevance": None,
    "newest": {"cludo-date": "desc"},
}


def _field_value(fields: Dict, name: str):
    """Unwrap one Cludo field entry into its plain value (or None)."""
    entry = fields.get(name)
    if entry is None:
        return None
    if entry.get("IsArray") and entry.get("Values") is not None:
        return entry["Values"]
    return entry.get("Value")


def _split_authors(fields: Dict) -> List[str]:
    authors = _field_value(fields, "authors")
    if authors is None:
        return []
    if isinstance(authors, list):
        return authors
    return [name.strip() for name in authors.split(",")]


def _iso_date(raw) -> Optional[str]:
    """Normalize Cludo dates ('Fri Nov 21, 2025 23:30:38 UTC', '11/21/2025 12:00:00 AM') to YYYY-MM-DD."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raw = str(raw)
    text = raw.strip()
    for fmt in ("%a %b %d, %Y %H:%M:%S %Z", "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw


def normalize_item(raw: dict) -> dict:
    """Map one Cludo TypedDocument to the public CLI record shape."""
    fields = raw.get("Fields", {})

    def _as_list(value):
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    subjects = _as_list(_field_value(fields, "course-category"))
    roles = _as_list(_field_value(fields, "roles"))

    rating = _field_value(fields, "rating")
    rating_count = _field_value(fields, "rating-count")

    # Pluralsight's search index has no dedicated tag taxonomy; the closest
    # tag-like data it exposes is subject area plus role tags.
    tags: List[str] = []
    for value in subjects + roles:
        if value and value not in tags:
            tags.append(value)

    def _int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _bool(value):
        if isinstance(value, str):
            return value.lower() == "true"
        return bool(value)

    skill_level = _field_value(fields, "Skill Levels")
    if isinstance(skill_level, list):
        skill_level = skill_level[0] if len(skill_level) == 1 else (", ".join(map(str, skill_level)) or None)
        if skill_level == "":
            skill_level = None
    category = _field_value(fields, "categories")
    # On paths/skills the "Skill Levels" field mirrors the path title instead
    # of holding a level; only keep it when it is a real level value.
    if category != "course" and skill_level == _field_value(fields, "Title"):
        skill_level = None
    valid_levels = {"Beginner", "Intermediate", "Advanced"}
    if skill_level not in valid_levels and category == "skill":
        skill_level = None

    return {
        "title": _field_value(fields, "Title"),
        "url": _field_value(fields, "Url"),
        "category": category,
        "subjects": subjects,
        "catalog": _field_value(fields, "course-catalog"),
        "roles": roles,
        "tags": tags,
        "authors": _split_authors(fields),
        "rating": float(rating) if rating not in (None, "") else None,
        "ratingCount": _int(rating_count),
        "publishedDate": _iso_date(_field_value(fields, "publish-date")),
        "updatedDate": _iso_date(_field_value(fields, "updated-date")),
        "duration": _field_value(fields, "duration"),
        "skillLevel": skill_level,
        "prodId": _field_value(fields, "prodId"),
        "numberOfLabs": _int(_field_value(fields, "numberOfLabs")),
        "numberOfCourses": _int(_field_value(fields, "numberOfCourses")),
        "retired": _bool(_field_value(fields, "retired")),
    }


class PluralsightClient:
    """Client for the public Pluralsight catalog search API."""

    def __init__(
        self,
        config=None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = config or get_config()
        self.base_url = self.config.base_url.rstrip("/")
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=UTF-8",
            "Authorization": SITE_AUTHORIZATION,
            "Referer": REFERER,
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
        if isinstance(body, dict) and "Message" in body:
            return str(body["Message"])
        return str(body)[:500]

    def _make_request(
        self,
        endpoint: str,
        data: Optional[Dict] = None,
        retry: bool = True,
    ) -> Dict:
        url = f"{self.base_url}{endpoint}"
        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None
        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                response = requests.post(url, headers=self.headers, json=data)
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

    def _search_raw(
        self,
        query: str,
        page: int,
        per_page: int,
        categories: List[str],
        sort: Optional[Dict],
    ) -> Dict:
        body: Dict = {
            "ResponseType": "json",
            "query": query,
            "page": page,
            "perPage": per_page,
            "operator": "and",
            "fields": REQUEST_FIELDS,
        }
        if categories:
            body["facets"] = {"categories": categories}
        if sort is not None:
            body["sort"] = sort
        return self._make_request("/search", data=body)

    @staticmethod
    def resolve_categories(category_options: List[str]) -> List[str]:
        """Resolve --category values to Cludo ``categories`` facet tokens.

        ``all`` removes the filter entirely; otherwise values map through
        CATEGORY_MAP and de-duplicate while preserving order.
        """
        resolved: List[str] = []
        for option in category_options:
            key = option.lower()
            if key == "all":
                return []
            if key not in CATEGORY_MAP:
                raise ClientError(
                    f"Invalid category '{option}'. Choose from: course, path, labs, certificate, all"
                )
            for token in CATEGORY_MAP[key]:
                if token not in resolved:
                    resolved.append(token)
        return resolved

    @cached
    def search_items(
        self,
        query: str,
        page: int = 1,
        per_page: int = 20,
        categories: Optional[List[str]] = None,
        sort: str = "relevance",
    ) -> Dict:
        """Keyword search over the public catalog; returns the full response.

        ``categories=None`` uses the same default content-type set as
        pluralsight.com/browse (courses, labs, certificates, skills);
        ``categories=[]`` searches every indexed content type.
        """
        return self._search_raw(
            query=query,
            page=page,
            per_page=per_page,
            categories=(
                list(DEFAULT_CATEGORIES)
                if categories is None
                else self.resolve_categories(categories)
            ),
            sort=SORT_MAP.get(sort, SORT_MAP["relevance"]),
        )

    @cached
    def list_items(
        self,
        page: int = 1,
        per_page: int = 20,
        categories: Optional[List[str]] = None,
    ) -> Dict:
        """List newest catalog entries (query '*' sorted by publish date desc)."""
        return self._search_raw(
            query="*",
            page=page,
            per_page=per_page,
            categories=(
                list(DEFAULT_CATEGORIES)
                if categories is None
                else self.resolve_categories(categories)
            ),
            sort=SORT_MAP["newest"],
        )

    @cached
    def get_item(self, item_id: str) -> Optional[dict]:
        """Fetch one catalog entry by product id via a server-side prodId query."""
        response = self._search_raw(
            query=f"prodId:{item_id}",
            page=1,
            per_page=5,
            categories=[],
            sort=SORT_MAP["relevance"],
        )
        documents = response.get("TypedDocuments") or []
        if not documents:
            return None
        return normalize_item(documents[0])

    @cached
    def get_suggestions(self, query: str) -> List[str]:
        """Return the search engine's query suggestions for a partial phrase."""
        response = self._search_raw(
            query=query,
            page=1,
            per_page=1,
            categories=[],
            sort=SORT_MAP["relevance"],
        )
        suggestions = response.get("Suggestions") or []
        result: List[str] = []
        for item in suggestions:
            value = item.get("Value") if isinstance(item, dict) else item
            if value:
                result.append(value)
        return result


_client: Optional[PluralsightClient] = None


def get_client() -> PluralsightClient:
    """Get or create the global Pluralsight client instance."""
    global _client
    if _client is None:
        _client = PluralsightClient()
    return _client
