"""USPS API client with OAuth 2.0 and exponential retry."""
from datetime import datetime
from typing import List, Optional
import random
import time
import requests

from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError
from .config import get_config
from .models import TrackingInfo, create_tracking_info


# Retry configuration defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_JITTER = 0.1  # 10% jitter

# HTTP status codes that trigger retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ClientError(Exception):
    """Custom exception for USPS API errors."""

    pass


class UspsClient:
    """Client for USPS Tracking API with OAuth 2.0 authentication."""

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
        config=None,
    ):
        """
        Initialize USPS client from configuration.

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
                "Run 'usps auth login' to authenticate."
            )

        # Retry configuration
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

        # Token caching
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[float] = None

    def _get_access_token(self) -> str:
        """
        Get OAuth 2.0 access token, using cached value if still valid.

        Returns:
            Access token string

        Raises:
            ClientError: If token request fails
        """
        # Return cached token if still valid (with 60s buffer)
        if (
            self._access_token
            and self._token_expiry
            and time.time() < self._token_expiry - 60
        ):
            return self._access_token

        # Request new token
        response = requests.post(
            self.config.oauth_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
            },
        )

        if not response.ok:
            raise ClientError(
                f"OAuth token request failed ({response.status_code}): {response.text}"
            )

        data = response.json()
        self._access_token = data["access_token"]
        # Token typically expires in 3600 seconds (1 hour)
        self._token_expiry = time.time() + data.get("expires_in", 3600)

        # Optionally save to config for persistence across CLI invocations
        self.config.save_access_token(
            self._access_token, str(int(self._token_expiry))
        )

        return self._access_token

    def _calculate_retry_delay(
        self, attempt: int, retry_after: Optional[float] = None
    ) -> float:
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
        delay = self.base_delay * (2**attempt)

        # Add random jitter to prevent thundering herd
        jitter_range = delay * self.jitter
        delay += random.uniform(-jitter_range, jitter_range)

        # Cap at max delay
        return min(delay, self.max_delay)

    def _is_retryable(
        self, response: Optional[requests.Response], exception: Optional[Exception]
    ) -> bool:
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
            return isinstance(
                exception,
                (
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.ChunkedEncodingError,
                ),
            )

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
            return float(retry_after)
        except ValueError:
            return None

    def _make_single_tracking_request(
        self, tracking_number: str, retry: bool = True
    ) -> dict:
        """
        Make a single tracking request to USPS API with exponential retry.

        The USPS Tracking API v3 uses GET requests with the tracking number
        in the URL path: /tracking/v3/tracking/{trackingNumber}?expand=DETAIL

        Args:
            tracking_number: Single tracking number to query
            retry: Whether to retry on transient errors (default: True)

        Returns:
            Tracking data dict from API

        Raises:
            ClientError: If request fails after all retries
        """
        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None

        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                # Get fresh token for each attempt in case it expired
                token = self._get_access_token()

                # USPS Tracking API v3 uses GET with tracking number in URL path
                url = f"{self.config.tracking_api_url}/{tracking_number}"
                response = requests.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                    params={"expand": "DETAIL"},
                )
                last_response = response

                # Check if we should retry this response
                if (
                    retry
                    and self._is_retryable(response, None)
                    and attempt < self.max_retries
                ):
                    retry_after = self._get_retry_after(response)
                    delay = self._calculate_retry_delay(attempt, retry_after)
                    time.sleep(delay)
                    continue

                # Success or non-retryable error - exit loop
                break

            except requests.exceptions.RequestException as e:
                last_exception = e
                # Check if we should retry this exception
                if (
                    retry
                    and self._is_retryable(None, e)
                    and attempt < self.max_retries
                ):
                    delay = self._calculate_retry_delay(attempt)
                    time.sleep(delay)
                    continue
                # Non-retryable exception or exhausted retries
                break

        # Handle the final result
        if last_exception is not None and last_response is None:
            raise ClientError(
                f"Request failed after {attempt + 1} attempts: {last_exception}"
            )

        if last_response is None:
            raise ClientError("Request failed: no response received")

        if not last_response.ok:
            try:
                error_data = last_response.json()
                error_msg = (
                    error_data.get("message")
                    or error_data.get("error")
                    or last_response.text
                )
            except Exception:
                error_msg = last_response.text
            raise ClientError(
                f"USPS API request failed ({last_response.status_code}): {error_msg}"
            )

        return last_response.json()

    def _make_tracking_request(
        self, tracking_numbers: List[str], retry: bool = True
    ) -> List[dict]:
        """
        Make tracking requests for multiple tracking numbers.

        The USPS Tracking API v3 only supports single tracking number queries,
        so this method makes sequential requests for each tracking number.

        Args:
            tracking_numbers: List of tracking numbers to query
            retry: Whether to retry on transient errors (default: True)

        Returns:
            List of tracking data dicts from API

        Raises:
            ClientError: If all requests fail
        """
        results = []
        for tracking_number in tracking_numbers:
            try:
                data = self._make_single_tracking_request(tracking_number, retry)
                results.append(data)
            except ClientError as e:
                # Include error info in results for batch processing
                results.append({
                    "trackingNumber": tracking_number,
                    "error": {"message": str(e)}
                })
        return results

    # ==================== API Methods ====================

    def get_tracking(self, tracking_number: str) -> TrackingInfo:
        """
        Get tracking information for a single package.

        Args:
            tracking_number: USPS tracking number

        Returns:
            TrackingInfo model with package details and events

        Raises:
            ClientError: If tracking request fails or tracking number is invalid
        """
        data = self._make_tracking_request([tracking_number])

        if not data or len(data) == 0:
            raise ClientError(f"No tracking data found for {tracking_number}")

        tracking_data = data[0]

        # Check for error in response
        if tracking_data.get("error"):
            error = tracking_data["error"]
            error_msg = (
                error.get("message") if isinstance(error, dict) else str(error)
            )
            raise ClientError(f"Tracking error for {tracking_number}: {error_msg}")

        return create_tracking_info(tracking_data)

    def get_tracking_batch(
        self,
        tracking_numbers: List[str],
        limit: Optional[int] = None,
        filters: Optional[List[str]] = None,
    ) -> List[TrackingInfo]:
        """
        Get tracking information for multiple packages.

        Args:
            tracking_numbers: List of USPS tracking numbers
            limit: Maximum number of results to return (applied after API call)
            filters: List of filter strings (field:op:value) - applied client-side

        Returns:
            List of TrackingInfo models

        Note:
            The USPS API does not support server-side filtering or limiting,
            so these are applied client-side after fetching all results.
        """
        if not tracking_numbers:
            return []

        # Apply limit at the query level if provided
        query_numbers = tracking_numbers
        if limit and limit < len(tracking_numbers):
            query_numbers = tracking_numbers[:limit]

        data = self._make_tracking_request(query_numbers)

        results = []
        for tracking_data in data:
            # Skip items with errors
            if tracking_data.get("error"):
                continue
            results.append(create_tracking_info(tracking_data))

        # Apply client-side filters if provided
        if filters:
            try:
                validate_filters(filters)
                # Convert models to dicts for filtering
                results_dicts = [r.model_dump() for r in results]
                filtered_dicts = apply_filters(results_dicts, filters)
                # Convert back to models
                results = [TrackingInfo(**d) for d in filtered_dicts]
            except FilterValidationError as e:
                raise ClientError(f"Invalid filter: {e}")

        return results

    def validate_credentials(self) -> bool:
        """
        Validate that credentials are valid by attempting to get a token.

        Returns:
            True if credentials are valid

        Raises:
            ClientError: If credentials are invalid
        """
        try:
            self._get_access_token()
            return True
        except Exception as e:
            raise ClientError(f"Invalid credentials: {e}")


# Module-level client instance - singleton pattern
_client: Optional[UspsClient] = None


def get_client() -> UspsClient:
    """Get or create the global USPS client instance."""
    global _client
    if _client is None:
        _client = UspsClient()
    return _client
