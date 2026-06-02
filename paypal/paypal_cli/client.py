"""PayPal API client with OAuth2 authentication."""
import base64
import time
from datetime import date, datetime, time as dt_time, timedelta, timezone
import re
from typing import Any, Dict, Iterator, List, Optional, Tuple

import requests

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import apply_filters, validate_filters
from .config import get_config


# Retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_TRANSACTION_PAGE_SIZE = 100
MAX_TRANSACTION_PAGE_SIZE = 500
MAX_TRANSACTION_WINDOW_DAYS = 31
_TRANSACTION_WINDOW_SPAN = timedelta(days=MAX_TRANSACTION_WINDOW_DAYS) - timedelta(seconds=1)
_DATE_ONLY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TZ_OFFSET_NO_COLON_PATTERN = re.compile(r"([+-]\d{2})(\d{2})$")


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

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Dict = None,
        params: Dict = None,
        retry: bool = True,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict:
        """Make authenticated API request with retry logic."""
        token = self.get_access_token()

        url = f"{self.base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)

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

    @staticmethod
    def _normalize_transaction_datetime(value: str, *, is_end: bool) -> datetime:
        """Normalize user-provided date/datetime input to a UTC datetime."""
        raw_value = value.strip()
        if not raw_value:
            raise ClientError("Date values cannot be empty.")

        if _DATE_ONLY_PATTERN.fullmatch(raw_value):
            try:
                parsed_date = date.fromisoformat(raw_value)
            except ValueError as exc:
                raise ClientError(
                    f"Invalid date value '{value}'. Use YYYY-MM-DD or an ISO-8601 datetime."
                ) from exc
            if is_end:
                return datetime.combine(parsed_date, dt_time(23, 59, 59), tzinfo=timezone.utc)
            return datetime.combine(parsed_date, dt_time(0, 0, 0), tzinfo=timezone.utc)

        normalized = raw_value.replace("Z", "+00:00")
        normalized = _TZ_OFFSET_NO_COLON_PATTERN.sub(r"\1:\2", normalized)
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ClientError(
                f"Invalid date value '{value}'. Use YYYY-MM-DD or an ISO-8601 datetime."
            ) from exc

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)
        return parsed.replace(microsecond=0)

    @classmethod
    def normalize_transaction_range(cls, start_date: str, end_date: str) -> Tuple[datetime, datetime]:
        """Normalize and validate a transaction date range."""
        normalized_start = cls._normalize_transaction_datetime(start_date, is_end=False)
        normalized_end = cls._normalize_transaction_datetime(end_date, is_end=True)
        if normalized_end < normalized_start:
            raise ClientError("end-date must be greater than or equal to start-date.")
        return normalized_start, normalized_end

    @staticmethod
    def format_transaction_datetime(value: datetime) -> str:
        """Format a UTC datetime for the PayPal reporting API."""
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @classmethod
    def iter_transaction_windows(
        cls, start_date: datetime, end_date: datetime
    ) -> Iterator[Tuple[datetime, datetime]]:
        """Yield inclusive transaction-search windows no larger than 31 days."""
        current_start = start_date
        while current_start <= end_date:
            current_end = min(current_start + _TRANSACTION_WINDOW_SPAN, end_date)
            yield current_start, current_end
            if current_end == end_date:
                break
            current_start = current_end + timedelta(seconds=1)

    def list_transactions(
        self,
        *,
        start_date: str,
        end_date: str,
        limit: int = 100,
        filters: Optional[List[str]] = None,
        page_size: int = DEFAULT_TRANSACTION_PAGE_SIZE,
        fields: str = "all",
        balance_affecting_records_only: str = "Y",
        transaction_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List transactions across one or more 31-day windows."""
        if limit <= 0:
            return []

        page_size = max(1, min(page_size, MAX_TRANSACTION_PAGE_SIZE))
        validate_filters(filters or [])
        normalized_start, normalized_end = self.normalize_transaction_range(start_date, end_date)

        transactions: List[Dict[str, Any]] = []
        for window_start, window_end in self.iter_transaction_windows(normalized_start, normalized_end):
            page = 1
            while True:
                remaining = limit - len(transactions)
                if remaining <= 0:
                    return transactions[:limit]

                request_page_size = page_size if filters else min(page_size, remaining)
                params = {
                    "start_date": self.format_transaction_datetime(window_start),
                    "end_date": self.format_transaction_datetime(window_end),
                    "fields": fields,
                    "page_size": request_page_size,
                    "page": page,
                    "balance_affecting_records_only": balance_affecting_records_only,
                }
                if transaction_id:
                    params["transaction_id"] = transaction_id

                response = self._make_request(
                    "GET",
                    "/v1/reporting/transactions",
                    params=params,
                    extra_headers={"PayPal-Enforce-ISO8601-Format": "true"},
                )

                page_transactions = response.get("transaction_details", [])
                if not page_transactions:
                    break

                if filters:
                    page_transactions = apply_filters(page_transactions, filters)

                transactions.extend(page_transactions)
                if len(transactions) >= limit:
                    return transactions[:limit]

                current_page = int(response.get("page", page))
                total_pages = int(response.get("total_pages", current_page))
                if current_page >= total_pages:
                    break
                page += 1

        return transactions[:limit]

    def get_transaction(
        self,
        *,
        transaction_id: str,
        start_date: str,
        end_date: str,
        page_size: int = DEFAULT_TRANSACTION_PAGE_SIZE,
        fields: str = "all",
        balance_affecting_records_only: str = "Y",
    ) -> Dict[str, Any]:
        """Get transaction-search matches for a PayPal transaction ID."""
        matches = self.list_transactions(
            start_date=start_date,
            end_date=end_date,
            limit=MAX_TRANSACTION_PAGE_SIZE,
            page_size=page_size,
            fields=fields,
            balance_affecting_records_only=balance_affecting_records_only,
            transaction_id=transaction_id,
        )
        return {
            "transaction_id": transaction_id,
            "transaction_details": matches,
            "matching_transaction_count": len(matches),
        }


# ==================== Client Factory ====================

_api_client: Optional[PayPalApiClient] = None


def get_api_client() -> PayPalApiClient:
    """Get or create the global API client instance."""
    global _api_client
    if _api_client is None:
        _api_client = PayPalApiClient()
    return _api_client
