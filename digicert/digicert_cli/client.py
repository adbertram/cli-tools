"""Digicert API client with automatic token management and exponential retry."""
from datetime import datetime
from typing import Dict, List, Optional, Any
import random
import time
import requests

from cli_tools_shared.filters import FilterValidationError, validate_filters

from .config import get_config
from .models import Item, ItemDetail, create_item, create_item_detail


# Retry configuration defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_JITTER = 0.1  # 10% jitter

# HTTP status codes that trigger retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


from cli_tools_shared.exceptions import ClientError


class DigicertClient:
    """Client for interacting with Digicert API with automatic token management and retry."""

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        """
        Initialize Digicert client from configuration.

        Args:
            max_retries: Maximum number of retry attempts for transient errors (default: 3)
            base_delay: Base delay in seconds for exponential backoff (default: 1.0)
            max_delay: Maximum delay in seconds between retries (default: 30.0)
            jitter: Random jitter factor to prevent thundering herd (default: 0.1)
        """
        self.config = get_config()

        # NOTE: For dual-auth CLIs (API + browser_session), replace has_credentials()
        # with a custom has_api_credentials() method that only checks API fields.
        # See auth-standards.md "API Client Credential Gate in Dual-Auth CLIs".
        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'digicert auth login' to authenticate."
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
        # Use Bearer token if available, otherwise PAT or API key
        if self.config.access_token:
            self.headers["Authorization"] = f"Bearer {self.config.access_token}"
        elif self.config.personal_access_token:
            self.headers["Authorization"] = f"Bearer {self.config.personal_access_token}"
        elif self.config.api_key:
            self.headers["Authorization"] = f"Bearer {self.config.api_key}"

    def _is_token_expired(self) -> bool:
        """Check if access token is expired or about to expire."""
        expires_at = self.config.token_expires_at
        if not expires_at:
            return False  # No expiry tracking, assume valid

        try:
            expires_timestamp = float(expires_at)
            # Consider expired if less than 5 minutes remaining
            return datetime.now().timestamp() > (expires_timestamp - 300)
        except (ValueError, TypeError):
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

    def _extract_error_detail(self, response: requests.Response) -> str:
        """Extract error detail from an HTTP error response.

        Handles multiple formats:
        - Nested: {"error": {"message": "..."}} or {"_error": {"Description": "..."}}
        - Simple: {"error": "..."} or {"message": "..."}
        - Fallback: raw response text
        """
        try:
            error_body = response.json()

            # Handle nested error formats (e.g., Dataverse _error.Description)
            if "_error" in error_body:
                err = error_body["_error"]
                if isinstance(err, dict):
                    return err.get("Description") or err.get("Message") or err.get("Code") or str(err)
                return str(err)

            # Handle standard error format
            if "error" in error_body:
                err = error_body["error"]
                if isinstance(err, dict):
                    return err.get("message") or err.get("code") or err.get("description") or str(err)
                return str(err)

            # Handle simple message field
            if "message" in error_body:
                return error_body["message"]

            # Fallback: stringify the whole body (truncated)
            return str(error_body)[:500]
        except Exception:
            # JSON parsing failed, use raw text
            return response.text[:500] if response.text else "Unknown error"

    def _refresh_token(self):
        """Refresh the access token using the refresh token."""
        refresh_token = self.config.refresh_token
        if not refresh_token:
            raise ClientError(
                "No refresh token available. Run 'digicert auth login' to re-authenticate."
            )

        # TODO: Implement token refresh for your specific API
        # token_url = f"{self.base_url}/oauth/token"
        # response = requests.post(token_url, data={...})
        # self.config.save_tokens(new_access, new_refresh, expires_at)
        # self._update_headers()
        raise ClientError("Token refresh not implemented. Run 'digicert auth login'.")

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retry: bool = True,
    ) -> Dict:
        """
        Make an HTTP request to the Digicert API with exponential retry.

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
            error_msg = self._extract_error_detail(last_response)
            raise ClientError(f"HTTP {last_response.status_code}: {error_msg}")

        # Handle empty response (204 No Content)
        if last_response.status_code == 204:
            return {}

        return last_response.json()

    # ==================== API Methods ====================
    # All methods return Pydantic models for type safety and validation

    def list_items(self, limit: int = 100, filters: Optional[List[str]] = None) -> List[Item]:
        """
        List items from the API.

        Limiting: API-level (uses 'limit' query param)
        Filtering: API-level where supported, client-side fallback

        Args:
            limit: Maximum number of items to return
            filters: List of filter strings (field:op:value)

        Returns:
            List of Item models
        """
        endpoint = "/items"  # TODO: Update endpoint
        params = {"limit": limit}  # TODO: Adjust param name for your API (per_page, limit, etc.)

        if filters:
            try:
                validate_filters(filters)
                # TODO: Translate filters to API params if supported
                # params["status"] = extract_filter_value(filters, "status")
            except FilterValidationError as e:
                raise ClientError(f"Invalid filter: {e}")

        response = self._make_request("GET", endpoint, params=params)

        # Extract array from wrapped response - adjust key for your API
        # Common patterns: response["data"], response["items"], response["results"]
        if isinstance(response, dict):
            raw_items = response.get("data", response.get("items", response.get("results", [])))
        else:
            raw_items = response

        # Convert to models
        items = [create_item(item) for item in raw_items]

        return items

    def get_item(self, item_id: str) -> ItemDetail:
        """
        Get a specific item by ID.

        Args:
            item_id: The item ID

        Returns:
            ItemDetail model with full details
        """
        endpoint = f"/items/{item_id}"  # TODO: Update endpoint
        response = self._make_request("GET", endpoint)

        # Extract item from wrapped response if needed
        if isinstance(response, dict) and "data" in response:
            raw_item = response["data"]
        else:
            raw_item = response

        return create_item_detail(raw_item)

    def search_items(
        self,
        query: str,
        limit: int = 100,
        fields: Optional[List[str]] = None,
    ) -> List[Item]:
        """
        Search items with wildcard matching.

        Search: API-level if search endpoint exists, otherwise client-side
        Wildcards: * matches any characters (fnmatch pattern)

        Args:
            query: Search query (supports * wildcards)
            limit: Maximum number of items to return
            fields: Optional list of fields to search (default: all string fields)

        Returns:
            List of matching Item models
        """
        import fnmatch

        # TODO: Check if API has a search endpoint
        # If so, use it:
        # endpoint = "/items/search"
        # params = {"q": query, "limit": limit}
        # response = self._make_request("GET", endpoint, params=params)
        # raw_items = response.get("data", response)
        # return [create_item(item) for item in raw_items]

        # Fall back to client-side wildcard matching
        items = self.list_items(limit=limit)

        # Convert query to fnmatch pattern (case-insensitive)
        pattern = query.lower()
        if '*' not in pattern:
            pattern = f'*{pattern}*'  # Default to contains match

        results = []
        for item in items:
            # Get item as dict for field access
            item_dict = item.model_dump()

            # Get fields to search
            search_fields = fields or [k for k, v in item_dict.items() if isinstance(v, str)]

            # Check if any field matches
            for field in search_fields:
                value = str(item_dict.get(field, '')).lower()
                if fnmatch.fnmatch(value, pattern):
                    results.append(item)
                    break

        return results


# Module-level client instance - singleton pattern
_client: Optional[DigicertClient] = None


def get_client() -> DigicertClient:
    """Get or create the global Digicert client instance."""
    global _client
    if _client is None:
        _client = DigicertClient()
    return _client
