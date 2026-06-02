"""Leanpub API client with exponential retry."""
from typing import Any, Dict, List, Optional
import random
import time
import warnings

warnings.filterwarnings("ignore", module="urllib3")
import requests
from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import FilterValidationError, apply_filters, validate_filters

from .config import get_config
from .models import (
    AuthorBookStats,
    AuthorStatsSummary,
    BookSummary,
    CurrentUser,
    RoyaltySummary,
    create_author_book_stats,
    create_book_summary,
    create_current_user,
    create_royalty_summary,
)


DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

activity = get_activity_logger("leanpub")


class LeanpubClient:
    """Client for documented Leanpub author API endpoints."""

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
                "Run 'leanpub auth login' to authenticate."
            )

        self.base_url = self.config.base_url.rstrip("/")
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """Calculate exponential retry delay for transient failures."""
        if retry_after is not None:
            return min(retry_after, self.max_delay)

        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        return min(delay + random.uniform(-jitter_range, jitter_range), self.max_delay)

    def _is_retryable(
        self,
        response: Optional[requests.Response],
        exception: Optional[Exception],
    ) -> bool:
        """Return whether a response or exception should be retried."""
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
        """Return Retry-After seconds when Leanpub provides that header."""
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return None

        try:
            return float(retry_after)
        except ValueError:
            return None

    def _extract_error_detail(self, response: requests.Response) -> str:
        """Extract Leanpub error details from an HTTP response."""
        try:
            error_body = response.json()
        except ValueError:
            return response.text[:500] if response.text else "Unknown error"

        if "errors" in error_body:
            return str(error_body["errors"])
        if "error" in error_body:
            return str(error_body["error"])
        if "message" in error_body:
            return str(error_body["message"])
        return str(error_body)[:500]

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        retry: bool = True,
    ) -> Any:
        """Make a Leanpub API request."""
        url = f"{self.base_url}{endpoint}"
        request_params = dict(params or {})
        request_data = dict(data or {})

        if method.upper() == "GET":
            request_params["api_key"] = self.config.api_key
        else:
            request_data["api_key"] = self.config.api_key

        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None
        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                activity.info("Leanpub request %s %s", method.upper(), endpoint)
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    json=request_data if request_data else None,
                    params=request_params,
                    timeout=30,
                )
                activity.info(
                    "Leanpub response %s %s -> %s",
                    method.upper(),
                    endpoint,
                    response.status_code,
                )
                last_response = response

                if retry and self._is_retryable(response, None) and attempt < self.max_retries:
                    delay = self._calculate_retry_delay(
                        attempt,
                        self._get_retry_after(response),
                    )
                    activity.warning(
                        "Retrying Leanpub request %s %s after %s seconds",
                        method.upper(),
                        endpoint,
                        delay,
                    )
                    time.sleep(delay)
                    continue

                break

            except requests.exceptions.RequestException as e:
                last_exception = e
                activity.warning(
                    "Leanpub request %s %s failed: %s",
                    method.upper(),
                    endpoint,
                    e,
                )
                if retry and self._is_retryable(None, e) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt))
                    continue
                break

        if last_exception is not None and last_response is None:
            raise ClientError(f"Request failed after {attempt + 1} attempts: {last_exception}")

        if last_response is None:
            raise ClientError("Request failed: no response received")

        if not last_response.ok:
            error_msg = self._extract_error_detail(last_response)
            raise ClientError(f"HTTP {last_response.status_code}: {error_msg}")

        if last_response.status_code == 204:
            return {}

        return last_response.json()

    def _resolve_slugs(self, slugs: Optional[List[str]]) -> List[str]:
        """Resolve explicit slugs or configured BOOK_SLUGS."""
        if slugs:
            resolved = [slug.strip() for slug in slugs]
            if any(not slug for slug in resolved):
                raise ClientError("--slug values must be non-empty.")
            return resolved

        configured = self.config.book_slugs
        if configured:
            return configured

        raise ClientError(
            "No Leanpub book slugs supplied. Pass --slug for each book or set BOOK_SLUGS "
            "in the active auth profile."
        )

    def get_current_user(self) -> CurrentUser:
        """Get the authenticated Leanpub user."""
        response = self._make_request("GET", "/current_user.json")
        return create_current_user(response)

    def get_book_summary(self, slug: str) -> BookSummary:
        """Get a Leanpub book summary."""
        response = self._make_request("GET", f"/{slug}.json")
        return create_book_summary(response)

    def get_royalties(self, slug: str) -> RoyaltySummary:
        """Get a Leanpub royalty summary for a book."""
        response = self._make_request("GET", f"/{slug}/royalties.json")
        return create_royalty_summary(response)

    def get_author_book_stats(self, slug: str) -> AuthorBookStats:
        """Get revenue and royalty stats for one book."""
        raw_summary = self._make_request("GET", f"/{slug}.json")
        raw_royalties = self._make_request("GET", f"/{slug}/royalties.json")
        summary = create_book_summary(raw_summary)
        royalties = create_royalty_summary(raw_royalties)
        return create_author_book_stats(summary, royalties, raw_summary, raw_royalties)

    def list_author_stats(
        self,
        slugs: Optional[List[str]] = None,
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[AuthorBookStats]:
        """List per-book author stats by looping over book slugs client-side."""
        if limit < 1:
            raise ClientError("--limit must be greater than 0.")

        resolved_slugs = self._resolve_slugs(slugs)
        selected_slugs = resolved_slugs[:limit]

        if filters:
            try:
                validate_filters(filters)
            except FilterValidationError as e:
                raise ClientError(f"Invalid filter: {e}")

        stats = [self.get_author_book_stats(slug) for slug in selected_slugs]
        if not filters:
            return stats

        filtered = apply_filters(
            [stat.model_dump(mode="json") for stat in stats],
            filters,
        )
        return [AuthorBookStats(**item) for item in filtered]

    def get_author_stats(self, slugs: Optional[List[str]] = None) -> AuthorStatsSummary:
        """Aggregate author stats across all supplied or configured slugs."""
        resolved_slugs = self._resolve_slugs(slugs)
        books = [self.get_author_book_stats(slug) for slug in resolved_slugs]

        return AuthorStatsSummary(
            book_count=len(books),
            total_revenue=sum(book.total_revenue for book in books),
            revenue_bundled=sum(book.revenue_bundled for book in books),
            revenue_unbundled=sum(book.revenue_unbundled for book in books),
            total_royalties=sum(book.total_royalties for book in books),
            royalties_bundled=sum(book.royalties_bundled for book in books),
            royalties_unbundled=sum(book.royalties_unbundled for book in books),
            last_week_royalties=sum(book.last_week_royalties for book in books),
            total_copies_sold=sum(book.total_copies_sold for book in books),
            num_copies_sold_bundled=sum(book.num_copies_sold_bundled for book in books),
            num_copies_sold_unbundled=sum(book.num_copies_sold_unbundled for book in books),
            books=books,
        )


_client: Optional[LeanpubClient] = None


def get_client() -> LeanpubClient:
    """Get or create the global Leanpub client instance."""
    global _client
    if _client is None:
        _client = LeanpubClient()
    return _client
