"""Hyvor API client with automatic token management and exponential retry."""
from datetime import datetime
from typing import Dict, List, Optional, Any
import json
import random
import time
import requests

from cli_tools_shared.filters import validate_filters, FilterValidationError
from .config import get_config
from .models import Comment, CommentDetail, create_comment, create_comment_detail


# Retry configuration defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_JITTER = 0.1  # 10% jitter

# HTTP status codes that trigger retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ClientError(Exception):
    """Custom exception for Hyvor API errors."""
    pass


class HyvorClient:
    """Client for interacting with Hyvor API with automatic token management and retry."""

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        """
        Initialize Hyvor client from configuration.

        Args:
            max_retries: Maximum number of retry attempts for transient errors (default: 3)
            base_delay: Base delay in seconds for exponential backoff (default: 1.0)
            max_delay: Maximum delay in seconds between retries (default: 30.0)
            jitter: Random jitter factor to prevent thundering herd (default: 0.1)
        """
        self.config = get_config()

        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'hyvor auth login' to authenticate."
            )

        self.base_url = self.config.base_url
        self._update_headers()

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
        # Hyvor uses X-API-KEY header for authentication
        if self.config.api_key:
            self.headers["X-API-KEY"] = self.config.api_key

    def _is_token_expired(self) -> bool:
        """Check if access token is expired or about to expire.

        Note: Hyvor uses API keys which don't expire, so this always returns False.
        """
        return False

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """
        Calculate delay before next retry using exponential backoff with jitter.

        Args:
            attempt: Current retry attempt number (0-indexed)
            retry_after: Optional Retry-After header value from server

        Returns:
            Delay in seconds before next retry
        """
        # Honor Retry-After header if present
        if retry_after is not None:
            return min(retry_after, self.max_delay)

        # Exponential backoff: base_delay * 2^attempt
        delay = self.base_delay * (2 ** attempt)

        # Add random jitter to prevent thundering herd
        jitter_range = delay * self.jitter
        delay += random.uniform(-jitter_range, jitter_range)

        # Cap at max delay
        return min(delay, self.max_delay)

    def _is_retryable(self, response: Optional[requests.Response], exception: Optional[Exception]) -> bool:
        """
        Determine if a request should be retried.

        Args:
            response: Response object (if request completed)
            exception: Exception raised (if request failed)

        Returns:
            True if request should be retried
        """
        # Retry on connection errors
        if exception is not None:
            return isinstance(exception, (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ))

        # Retry on specific status codes
        if response is not None:
            return response.status_code in RETRYABLE_STATUS_CODES

        return False

    def _get_retry_after(self, response: requests.Response) -> Optional[float]:
        """
        Extract Retry-After header value from response.

        Args:
            response: Response object

        Returns:
            Retry delay in seconds, or None if not present
        """
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return None

        try:
            # Try parsing as integer seconds
            return float(retry_after)
        except ValueError:
            # Could be HTTP-date format, but we'll skip that complexity
            return None

    def _refresh_token(self):
        """Refresh is not applicable for Hyvor API key authentication."""
        # Hyvor uses static API keys - no token refresh needed
        pass

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retry: bool = True,
    ) -> Dict:
        """
        Make an HTTP request to the Hyvor API with exponential retry.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            endpoint: API endpoint path (e.g., "/users")
            data: Request body data
            params: Query parameters
            retry: Whether to retry on transient errors (default: True)

        Returns:
            Response JSON data

        Raises:
            ClientError: If request fails after all retries
        """
        url = f"{self.base_url}{endpoint}"

        # Check if token needs refresh
        if self._is_token_expired():
            try:
                self._refresh_token()
            except Exception:
                pass  # Try with existing token

        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None

        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                # Make the request
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    json=data,
                    params=params,
                )
                last_response = response

                # If 401, try refreshing token and retry (doesn't count against retry limit)
                if response.status_code == 401:
                    try:
                        self._refresh_token()
                        response = requests.request(
                            method=method,
                            url=url,
                            headers=self.headers,
                            json=data,
                            params=params,
                        )
                        last_response = response
                    except Exception as e:
                        raise ClientError(f"Authentication failed: {e}")

                # Check if we should retry this response
                if retry and self._is_retryable(response, None) and attempt < self.max_retries:
                    retry_after = self._get_retry_after(response)
                    delay = self._calculate_retry_delay(attempt, retry_after)
                    time.sleep(delay)
                    continue

                # Success or non-retryable error - exit loop
                break

            except requests.exceptions.RequestException as e:
                last_exception = e
                # Check if we should retry this exception
                if retry and self._is_retryable(None, e) and attempt < self.max_retries:
                    delay = self._calculate_retry_delay(attempt)
                    time.sleep(delay)
                    continue
                # Non-retryable exception or exhausted retries
                break

        # Handle the final result
        if last_exception is not None and last_response is None:
            raise ClientError(f"Request failed after {attempt + 1} attempts: {last_exception}")

        if last_response is None:
            raise ClientError("Request failed: no response received")

        if not last_response.ok:
            # Try to get error details from response
            try:
                error_data = last_response.json()
                error_msg = error_data.get("message") or error_data.get("error") or last_response.text
            except Exception:
                error_msg = last_response.text
            raise ClientError(f"API request failed ({last_response.status_code}): {error_msg}")

        # Handle empty response (204 No Content)
        if last_response.status_code == 204:
            return {}

        return last_response.json()

    # ==================== API Methods ====================
    # All methods return Pydantic models for type safety and validation

    def list_comments(
        self,
        website_id: int,
        limit: int = 100,
        offset: int = 0,
        comment_type: Optional[str] = None,
        comment_filter: Optional[str] = None,
        filters: Optional[List[str]] = None,
    ) -> List[Comment]:
        """
        List comments for a website.

        Args:
            website_id: The Hyvor website ID
            limit: Maximum number of comments to return
            offset: Pagination offset
            comment_type: Filter by type - published, pending, deleted, spam, flagged
            comment_filter: API filter - unreplied, unread, guest, has_questions, has_links, has_media
            filters: List of filter strings (field:op:value) for client-side filtering

        Returns:
            List of Comment models
        """
        endpoint = f"/{website_id}/comments"
        params = {"limit": limit, "offset": offset}

        # Add type filter if specified
        # API uses 'type' query param with values: published, pending, deleted, spam, flagged
        if comment_type:
            type_map = {
                "approved": "published",
                "published": "published",
                "pending": "pending",
                "deleted": "deleted",
                "spam": "spam",
                "flagged": "flagged",
            }
            params["type"] = type_map.get(comment_type.lower(), comment_type)

        # Add comment filter if specified
        # API uses 'filter' param with values: unread, unreplied, guest, has_questions, has_links, has_media
        if comment_filter:
            params["filter"] = comment_filter

        if filters:
            try:
                validate_filters(filters)
            except FilterValidationError as e:
                raise ClientError(f"Invalid filter: {e}")

        response = self._make_request("GET", endpoint, params=params)

        # Hyvor returns array directly
        if isinstance(response, list):
            raw_comments = response
        elif isinstance(response, dict) and "comments" in response:
            raw_comments = response["comments"]
        else:
            raw_comments = []

        # Convert to models
        comments = [create_comment(comment) for comment in raw_comments]

        return comments

    def get_replied_parent_ids(self, website_id: int) -> set:
        """
        Get IDs of comments that have been replied to by moderators.

        Workaround for Hyvor API bug where has_mod_replied is not updated
        when replying via Console API.

        Args:
            website_id: The Hyvor website ID

        Returns:
            Set of parent comment IDs that have moderator replies
        """
        endpoint = f"/{website_id}/comments"
        params = {"limit": 100, "type": "published"}

        response = self._make_request("GET", endpoint, params=params)

        if isinstance(response, list):
            raw_comments = response
        elif isinstance(response, dict) and "comments" in response:
            raw_comments = response["comments"]
        else:
            raw_comments = []

        # Extract parent IDs from comments by moderators (owner/moderator role)
        replied_ids = set()
        for comment in raw_comments:
            user = comment.get("user", {})
            parent = comment.get("parent")
            role = user.get("role") if user else None

            if role in ("owner", "moderator") and parent:
                parent_id = parent.get("id") if isinstance(parent, dict) else parent
                if parent_id:
                    replied_ids.add(parent_id)

        return replied_ids

    def get_comment(self, website_id: int, comment_id: int) -> CommentDetail:
        """
        Get a specific comment by ID.

        Args:
            website_id: The Hyvor website ID
            comment_id: The comment ID

        Returns:
            CommentDetail model with full details
        """
        endpoint = f"/{website_id}/comment/{comment_id}"
        response = self._make_request("GET", endpoint)

        # Extract comment from wrapped response if needed
        if isinstance(response, dict) and "comment" in response:
            raw_comment = response["comment"]
        else:
            raw_comment = response

        return create_comment_detail(raw_comment)

    def reply_to_comment(self, website_id: int, comment_id: int, body: str) -> CommentDetail:
        """
        Reply to a specific comment.

        Args:
            website_id: The Hyvor website ID
            comment_id: The comment ID to reply to
            body: Reply body text

        Returns:
            CommentDetail model of the reply
        """
        endpoint = f"/{website_id}/comment/{comment_id}/reply"
        # Hyvor API expects body in ProseMirror JSON format
        # Convert plain text to a ProseMirror document structure
        prosemirror_doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": body
                        }
                    ]
                }
            ]
        }
        data = {"body": json.dumps(prosemirror_doc)}

        response = self._make_request("POST", endpoint, data=data)

        # Extract reply from response
        if isinstance(response, dict) and "comment" in response:
            raw_reply = response["comment"]
        else:
            raw_reply = response

        return create_comment_detail(raw_reply)

    def update_comment(
        self, website_id: int, comment_id: int, body: Optional[str] = None, status: Optional[str] = None
    ) -> CommentDetail:
        """
        Update a comment's body or status.

        Args:
            website_id: The Hyvor website ID
            comment_id: The comment ID to update
            body: New comment body (optional)
            status: New comment status (optional)

        Returns:
            CommentDetail model with updated data
        """
        endpoint = f"/{website_id}/comment/{comment_id}"
        data = {}

        if body is not None:
            data["body"] = body
        if status is not None:
            data["status"] = status

        if not data:
            raise ClientError("No fields to update (body or status required)")

        response = self._make_request("PATCH", endpoint, data=data)

        # Extract comment from response
        if isinstance(response, dict) and "comment" in response:
            raw_comment = response["comment"]
        else:
            raw_comment = response

        return create_comment_detail(raw_comment)

    def delete_comment(self, website_id: int, comment_id: int) -> None:
        """
        Delete a comment.

        Args:
            website_id: The Hyvor website ID
            comment_id: The comment ID to delete
        """
        endpoint = f"/{website_id}/comment/{comment_id}"
        self._make_request("DELETE", endpoint)


# Module-level client instance - singleton pattern
_client: Optional[HyvorClient] = None


def get_client() -> HyvorClient:
    """Get or create the global Hyvor client instance."""
    global _client
    if _client is None:
        _client = HyvorClient()
    return _client
