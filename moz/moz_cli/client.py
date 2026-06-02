"""Moz API client using JSON-RPC 2.0 with exponential retry."""
from typing import Dict, List, Optional, Any
import random
import time
import uuid
import requests

from cli_tools_shared.filters import FilterValidationError, validate_filters
from .config import get_config
from .models import (
    KeywordMetrics,
    KeywordDetail,
    SuggestionKeyword,
    SearchIntent,
    RankingKeyword,
    create_keyword_metrics,
    create_keyword_detail,
    create_suggestion_keyword,
    create_search_intent,
    create_ranking_keyword,
)


# Retry configuration defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_JITTER = 0.1  # 10% jitter

# HTTP status codes that trigger retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ClientError(Exception):
    """Custom exception for Moz API errors."""
    pass


class MozClient:
    """Client for interacting with Moz API (JSON-RPC 2.0) with retry."""

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
        config=None,
    ):
        """
        Initialize Moz client from configuration.

        Args:
            max_retries: Maximum number of retry attempts for transient errors (default: 3)
            base_delay: Base delay in seconds for exponential backoff (default: 1.0)
            max_delay: Maximum delay in seconds between retries (default: 30.0)
            jitter: Random jitter factor to prevent thundering herd (default: 0.1)
        """
        self.config = config or get_config()

        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'moz auth login' to authenticate."
            )

        self.base_url = self.config.base_url
        self._update_headers()
        self._request_id = 0

        # Retry configuration
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

    def _update_headers(self):
        """Update request headers with current credentials."""
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        # Use API key for authentication with x-moz-token header (per Moz API docs)
        if self.config.api_key:
            self.headers["x-moz-token"] = self.config.api_key

    def _get_next_request_id(self) -> str:
        """Get next JSON-RPC request ID (UUID per Moz API docs - must be 24+ chars)."""
        return str(uuid.uuid4())

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """
        Calculate delay before next retry using exponential backoff with jitter.

        Args:
            attempt: Current retry attempt number (0-indexed)
            retry_after: Optional Retry-After header value from server

        Returns:
            Delay in seconds before next retry
        """
        if retry_after is not None:
            return min(retry_after, self.max_delay)

        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        delay += random.uniform(-jitter_range, jitter_range)
        return min(delay, self.max_delay)

    def _is_retryable(self, response: Optional[requests.Response], exception: Optional[Exception]) -> bool:
        """Determine if a request should be retried."""
        if exception is not None:
            return isinstance(exception, (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ))

        if response is not None:
            return response.status_code in RETRYABLE_STATUS_CODES

        return False

    def _get_retry_after(self, response: requests.Response) -> Optional[float]:
        """Extract Retry-After header value from response."""
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return None

        try:
            return float(retry_after)
        except ValueError:
            return None

    def _make_jsonrpc_request(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        retry: bool = True,
    ) -> Dict:
        """
        Make a JSON-RPC 2.0 request to Moz API with exponential retry.

        Args:
            method: JSON-RPC method name
            params: Method parameters
            retry: Whether to retry on transient errors (default: True)

        Returns:
            Response result data

        Raises:
            ClientError: If request fails after all retries
        """
        request_id = self._get_next_request_id()
        # Moz API requires params to be wrapped in a "data" object
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": {"data": params} if params else {},
        }

        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None
        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                response = requests.post(
                    self.base_url,
                    headers=self.headers,
                    json=payload,
                )
                last_response = response

                # Check if we should retry this response
                if retry and self._is_retryable(response, None) and attempt < self.max_retries:
                    retry_after = self._get_retry_after(response)
                    delay = self._calculate_retry_delay(attempt, retry_after)
                    time.sleep(delay)
                    continue

                break

            except requests.exceptions.RequestException as e:
                last_exception = e
                if retry and self._is_retryable(None, e) and attempt < self.max_retries:
                    delay = self._calculate_retry_delay(attempt)
                    time.sleep(delay)
                    continue
                break

        # Handle the final result
        if last_exception is not None and last_response is None:
            raise ClientError(f"Request failed after {attempt + 1} attempts: {last_exception}")

        if last_response is None:
            raise ClientError("Request failed: no response received")

        if not last_response.ok:
            try:
                error_data = last_response.json()
                error_msg = error_data.get("error", {}).get("message") or last_response.text
            except Exception:
                error_msg = last_response.text
            raise ClientError(f"API request failed ({last_response.status_code}): {error_msg}")

        # Parse JSON-RPC response
        try:
            response_data = last_response.json()
        except Exception as e:
            raise ClientError(f"Failed to parse response: {e}")

        # Check for JSON-RPC error
        if "error" in response_data and response_data["error"] is not None:
            error = response_data["error"]
            error_msg = error.get("message", str(error))
            raise ClientError(f"API error: {error_msg}")

        # Return the result
        return response_data.get("result", {})

    # ==================== API Methods ====================
    # All methods return Pydantic models for type safety

    def get_keyword_metrics(self, keyword: str, locale: str = "en-US", device: str = "desktop", engine: str = "google") -> KeywordMetrics:
        """
        Get metrics for a single keyword.

        Args:
            keyword: The keyword to look up
            locale: Locale for search (default: en-US)
            device: Device type (default: desktop)
            engine: Search engine (default: google)

        Returns:
            KeywordMetrics model
        """
        # Use full metrics fetch which returns all keyword metrics
        response = self._make_jsonrpc_request(
            "data.keyword.metrics.fetch",
            {
                "serp_query": {
                    "keyword": keyword,
                    "locale": locale,
                    "device": device,
                    "engine": engine,
                }
            },
        )
        # Extract keyword_metrics from response and add keyword
        metrics = response.get("keyword_metrics", {})
        metrics["keyword"] = keyword
        return create_keyword_metrics(metrics)

    def get_keyword_suggestions(self, keyword: str, locale: str = "en-US", device: str = "desktop", engine: str = "google") -> List[SuggestionKeyword]:
        """
        Get suggested related keywords.

        Args:
            keyword: The base keyword
            locale: Locale for search (default: en-US)
            device: Device type (default: desktop)
            engine: Search engine (default: google)

        Returns:
            List of SuggestionKeyword models
        """
        response = self._make_jsonrpc_request(
            "data.keyword.suggestions.list",
            {
                "serp_query": {
                    "keyword": keyword,
                    "locale": locale,
                    "device": device,
                    "engine": engine,
                }
            },
        )

        # Extract suggestions array
        suggestions = response.get("suggestions", [])
        results = []
        for suggestion in suggestions:
            suggestion["related_to"] = keyword
            results.append(create_suggestion_keyword(suggestion))

        return results

    def get_search_intent(self, keyword: str, locale: str = "en-US", device: str = "desktop", engine: str = "google") -> SearchIntent:
        """
        Get search intent for a keyword.

        Args:
            keyword: The keyword to analyze
            locale: Locale for search (default: en-US)
            device: Device type (default: desktop)
            engine: Search engine (default: google)

        Returns:
            SearchIntent model
        """
        response = self._make_jsonrpc_request(
            "data.keyword.search.intent.fetch",
            {
                "serp_query": {
                    "keyword": keyword,
                    "locale": locale,
                    "device": device,
                    "engine": engine,
                }
            },
        )
        # Extract keyword_intent from response
        intent = response.get("keyword_intent", {})
        intent["keyword"] = keyword
        return create_search_intent(intent)

    def get_ranking_keywords(self, url: str, scope: str = "url", locale: str = "en-US", engine: str = "google", limit: int = 100) -> List[RankingKeyword]:
        """
        Get keywords a URL ranks for.

        Args:
            url: The URL/site to analyze
            scope: Query scope: domain, subdomain, subfolder, or url (default: url)
            locale: Locale for search (default: en-US)
            engine: Search engine (default: google)
            limit: Maximum results to return (default: 100)

        Returns:
            List of RankingKeyword models
        """
        response = self._make_jsonrpc_request(
            "data.site.ranking.keywords.list",
            {
                "target_query": {
                    "query": url,
                    "scope": scope,
                    "locale": locale,
                },
                "serp_query": {
                    "engine": engine,
                    "locale": locale,
                },
                "limit": limit,
            },
        )

        # Moz returns ranking keywords under "ranking_keywords"
        keywords = response.get("ranking_keywords", [])
        results = []
        for kw in keywords:
            kw["url"] = url
            results.append(create_ranking_keyword(kw))

        return results


# Module-level client instance - singleton pattern
_client: Optional[MozClient] = None


def get_client() -> MozClient:
    """Get or create the global Moz client instance."""
    global _client
    if _client is None:
        _client = MozClient()
    return _client
