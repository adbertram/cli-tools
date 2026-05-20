"""X API client with OAuth 1.0a authentication for posting tweets."""
from typing import Dict, Optional
import random
import time
import requests
from requests_oauthlib import OAuth1

from .config import get_config
from .models import Tweet, create_tweet


# Retry configuration defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_JITTER = 0.1  # 10% jitter

# HTTP status codes that trigger retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ClientError(Exception):
    """Custom exception for X API errors."""
    pass


class XClient:
    """Client for interacting with X API v2 using OAuth 1.0a authentication.

    X API v2 requires OAuth 1.0a User Context for posting tweets.
    See: https://docs.x.com/x-api/posts/creation-of-a-post
    """

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
        config=None,
    ):
        """
        Initialize X client from configuration.

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
                "Run `x auth login` to configure them."
            )

        self.base_url = self.config.base_url

        # Set up OAuth 1.0a authentication
        self.oauth = OAuth1(
            client_key=self.config.consumer_key,
            client_secret=self.config.consumer_secret,
            resource_owner_key=self.config.access_token,
            resource_owner_secret=self.config.access_token_secret,
        )

        # Retry configuration
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

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
            return float(retry_after)
        except ValueError:
            return None

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retry: bool = True,
    ) -> Dict:
        """
        Make an HTTP request to the X API v2 with OAuth 1.0a and exponential retry.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            endpoint: API endpoint path (e.g., "/2/tweets")
            data: Request body data (JSON)
            params: Query parameters
            retry: Whether to retry on transient errors (default: True)

        Returns:
            Response JSON data

        Raises:
            ClientError: If request fails after all retries
        """
        url = f"{self.base_url}{endpoint}"

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None

        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                # Make the request with OAuth 1.0a
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=data,
                    params=params,
                    auth=self.oauth,
                )
                last_response = response

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
                # X API v2 error format
                if "errors" in error_data:
                    errors = error_data["errors"]
                    error_msg = "; ".join(e.get("message", str(e)) for e in errors)
                elif "detail" in error_data:
                    error_msg = error_data["detail"]
                elif "title" in error_data:
                    error_msg = f"{error_data['title']}: {error_data.get('detail', '')}"
                else:
                    error_msg = last_response.text
            except Exception:
                error_msg = last_response.text
            raise ClientError(f"API request failed ({last_response.status_code}): {error_msg}")

        # Handle empty response (204 No Content)
        if last_response.status_code == 204:
            return {}

        return last_response.json()

    # ==================== Tweet Methods ====================

    def post_tweet(
        self,
        text: str,
        reply_to: Optional[str] = None,
        quote_tweet_id: Optional[str] = None,
    ) -> Tweet:
        """
        Post a tweet to X.

        Args:
            text: The text content of the tweet (max 280 characters)
            reply_to: Optional tweet ID to reply to
            quote_tweet_id: Optional tweet ID to quote

        Returns:
            Tweet model with the created tweet data

        Raises:
            ClientError: If the request fails
        """
        if len(text) > 280:
            raise ClientError(f"Tweet text exceeds 280 characters ({len(text)} chars)")

        endpoint = "/2/tweets"
        payload: Dict = {"text": text}

        if reply_to:
            payload["reply"] = {"in_reply_to_tweet_id": reply_to}

        if quote_tweet_id:
            payload["quote_tweet_id"] = quote_tweet_id

        response = self._make_request("POST", endpoint, data=payload)

        # X API v2 returns {"data": {"id": "...", "text": "..."}}
        tweet_data = response.get("data", response)
        return create_tweet(tweet_data)

    def delete_tweet(self, tweet_id: str) -> bool:
        """
        Delete a tweet.

        Args:
            tweet_id: The ID of the tweet to delete

        Returns:
            True if deletion was successful

        Raises:
            ClientError: If the request fails
        """
        endpoint = f"/2/tweets/{tweet_id}"
        response = self._make_request("DELETE", endpoint)

        # X API v2 returns {"data": {"deleted": true}}
        return response.get("data", {}).get("deleted", False)

    def get_tweet(self, tweet_id: str) -> Tweet:
        """
        Get a tweet by ID.

        Args:
            tweet_id: The ID of the tweet to retrieve

        Returns:
            Tweet model with the tweet data

        Raises:
            ClientError: If the request fails
        """
        endpoint = f"/2/tweets/{tweet_id}"
        params = {"tweet.fields": "created_at,author_id,public_metrics"}
        response = self._make_request("GET", endpoint, params=params)

        tweet_data = response.get("data", response)
        return create_tweet(tweet_data)

    def get_me(self) -> Dict:
        """
        Get the authenticated user's information.

        Returns:
            Dict with user data including id

        Raises:
            ClientError: If the request fails
        """
        endpoint = "/2/users/me"
        response = self._make_request("GET", endpoint)
        return response.get("data", response)

    def list_tweets(self, limit: int = 100) -> list:
        """
        List tweets from the authenticated user's timeline.

        Args:
            limit: Maximum number of tweets to return (5-100, default: 100)

        Returns:
            List of Tweet models

        Raises:
            ClientError: If the request fails
        """
        # First get the authenticated user's ID
        user_data = self.get_me()
        user_id = user_data.get("id")

        if not user_id:
            raise ClientError("Failed to get authenticated user ID")

        # Now get their tweets
        endpoint = f"/2/users/{user_id}/tweets"
        params = {
            "max_results": min(max(5, limit), 100),  # API enforces 5-100 range
            "tweet.fields": "created_at,author_id,public_metrics"
        }
        response = self._make_request("GET", endpoint, params=params)

        tweets_data = response.get("data", [])
        return [create_tweet(tweet_data) for tweet_data in tweets_data]


# Module-level client instance - singleton pattern
_client: Optional[XClient] = None


def get_client() -> XClient:
    """Get or create the global X client instance."""
    global _client
    if _client is None:
        _client = XClient()
    return _client
