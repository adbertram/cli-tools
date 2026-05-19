"""PayPal API client with OAuth2 authentication.

Provides:
- OAuth2 API client for REST API authentication
"""
import base64
import time
from typing import Dict, List, Optional

import requests

from cli_tools_shared.exceptions import ClientError
from .config import get_config


# Retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds


def _calculate_retry_delay(attempt: int, base_delay: float = DEFAULT_BASE_DELAY) -> float:
    """Calculate retry delay with exponential backoff and jitter."""
    import random
    delay = base_delay * (2 ** attempt)
    jitter = random.uniform(0, delay * 0.1)
    return delay + jitter


# ==================== API Client ====================

class PayPalApiClient:
    """Client for PayPal REST API with OAuth2 authentication."""

    def __init__(self):
        """Initialize PayPal API client."""
        self.config = get_config()

        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing API credentials: {', '.join(missing)}. "
                "Add them to your .env file."
            )

        self.base_url = self.config.api_base_url
        self._access_token = self.config.access_token
        self._token_expires_at = None

        # Parse stored expiration if available
        if self.config.token_expires_at:
            try:
                self._token_expires_at = float(self.config.token_expires_at)
            except ValueError:
                pass

    def _is_token_expired(self) -> bool:
        """Check if access token is expired or about to expire."""
        if not self._access_token or not self._token_expires_at:
            return True
        # Consider expired if less than 60 seconds remaining
        return time.time() > (self._token_expires_at - 60)

    def authenticate(self) -> Dict:
        """Authenticate with PayPal API using client credentials."""
        credentials = base64.b64encode(
            f"{self.config.client_id}:{self.config.client_secret}".encode()
        ).decode()

        response = requests.post(
            f"{self.base_url}/v1/oauth2/token",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json"
            },
            data="grant_type=client_credentials"
        )

        if not response.ok:
            raise ClientError(f"PayPal authentication failed: {response.status_code} - {response.text}")

        data = response.json()
        self._access_token = data["access_token"]
        # Set expiration with 60 second buffer
        self._token_expires_at = time.time() + data["expires_in"] - 60

        # Save tokens to config
        self.config.save_tokens(
            self._access_token,
            str(self._token_expires_at)
        )

        return {
            "access_token": data["access_token"],
            "token_type": data["token_type"],
            "app_id": data.get("app_id"),
            "expires_in": data["expires_in"],
            "scope": data.get("scope", "")
        }

    def get_access_token(self) -> str:
        """Get valid access token, refreshing if needed."""
        if self._is_token_expired():
            self.authenticate()
        return self._access_token

    def _make_request(self, method: str, endpoint: str, data: Dict = None, params: Dict = None, retry: bool = True) -> Dict:
        """Make authenticated API request with retry logic."""
        token = self.get_access_token()

        url = f"{self.base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        max_retries = DEFAULT_MAX_RETRIES if retry else 1
        last_error = None

        for attempt in range(max_retries):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=data,
                    params=params
                )

                # Check for retry-able errors
                if response.status_code == 429:
                    retry_after = response.headers.get('Retry-After')
                    if retry_after:
                        time.sleep(float(retry_after))
                    elif attempt < max_retries - 1:
                        time.sleep(_calculate_retry_delay(attempt))
                    continue

                if response.status_code >= 500 and attempt < max_retries - 1:
                    time.sleep(_calculate_retry_delay(attempt))
                    continue

                if not response.ok:
                    raise ClientError(f"PayPal API error: {response.status_code} - {response.text}")

                if response.status_code == 204:
                    return {}

                return response.json()

            except (requests.ConnectionError, requests.Timeout) as e:
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(_calculate_retry_delay(attempt))
                    continue
                raise ClientError(f"Connection error after {max_retries} retries: {e}")

        raise ClientError(f"Request failed after {max_retries} retries")

    def get(self, endpoint: str, params: Dict = None) -> Dict:
        """GET request to PayPal API."""
        return self._make_request("GET", endpoint, params=params)

    def post(self, endpoint: str, data: Dict = None) -> Dict:
        """POST request to PayPal API."""
        return self._make_request("POST", endpoint, data=data)

    def create_payout(self, items: List[Dict], email_subject: str = None, email_message: str = None) -> Dict:
        """Create a batch payout."""
        import uuid
        sender_batch_id = str(uuid.uuid4())[:30]
        payload = {
            "sender_batch_header": {
                "sender_batch_id": sender_batch_id,
                "recipient_type": "EMAIL",
            },
            "items": items
        }
        if email_subject:
            payload["sender_batch_header"]["email_subject"] = email_subject
        if email_message:
            payload["sender_batch_header"]["email_message"] = email_message
        return self.post("/v1/payments/payouts", data=payload)

    def get_payout(self, payout_batch_id: str) -> Dict:
        """Get batch payout details."""
        return self.get(f"/v1/payments/payouts/{payout_batch_id}")

    def get_payout_item(self, payout_item_id: str) -> Dict:
        """Get payout item details."""
        return self.get(f"/v1/payments/payouts-item/{payout_item_id}")

    def cancel_payout_item(self, payout_item_id: str) -> Dict:
        """Cancel an unclaimed payout item."""
        return self.post(f"/v1/payments/payouts-item/{payout_item_id}/cancel")


# ==================== Client Factory ====================

_api_client: Optional[PayPalApiClient] = None


def get_api_client() -> PayPalApiClient:
    """Get or create the global API client instance."""
    global _api_client
    if _api_client is None:
        _api_client = PayPalApiClient()
    return _api_client
