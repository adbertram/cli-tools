"""FedEx Pickup API client with OAuth token management and exponential retry."""
from datetime import datetime
from typing import Dict, List, Optional, Any
import random
import time
import requests
import uuid

from .config import get_config
from .models import (
    Pickup,
    PickupAvailabilityOption,
    PickupRequest,
    CancelPickupRequest,
    PickupAddress,
    create_pickup,
    create_availability_options,
)


# Retry configuration defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_JITTER = 0.1  # 10% jitter

# HTTP status codes that trigger retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ClientError(Exception):
    """Custom exception for Fedex API errors."""
    pass


class FedexClient:
    """Client for interacting with FedEx Pickup API with OAuth token management and retry."""

    def __init__(
        self,
        require_auth: bool = True,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        """
        Initialize FedEx client from configuration.

        Args:
            require_auth: Whether to require authentication (default: True, set False for login flow)
            max_retries: Maximum number of retry attempts for transient errors (default: 3)
            base_delay: Base delay in seconds for exponential backoff (default: 1.0)
            max_delay: Maximum delay in seconds between retries (default: 30.0)
            jitter: Random jitter factor to prevent thundering herd (default: 0.1)
        """
        self.config = get_config()
        self.base_url = self.config.base_url

        if require_auth:
            if not self.config.has_credentials():
                missing = self.config.get_missing_credentials()
                raise ClientError(
                    f"Missing credentials: {', '.join(missing)}. "
                    "Run 'fedex auth login' to authenticate."
                )
            self._refresh_oauth_token()

        self._update_headers()

        # Retry configuration
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

    def _update_headers(self):
        """Update request headers with current access token."""
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.config.access_token:
            self.headers["Authorization"] = f"Bearer {self.config.access_token}"

    def _refresh_oauth_token(self):
        """Get or refresh OAuth access token using client credentials."""
        oauth_url = f"{self.base_url}/oauth/token"

        payload = {
            "grant_type": "client_credentials",
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
        }

        try:
            response = requests.post(
                oauth_url,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
            response.raise_for_status()

            token_data = response.json()
            access_token = token_data.get("access_token")
            expires_in = token_data.get("expires_in", 3600)

            if not access_token:
                raise ClientError("No access token in OAuth response")

            # Save tokens with expiration time (55 minutes to be safe)
            import time as time_module
            expires_at = time_module.time() + (expires_in * 0.917)  # 55/60 of the full duration
            self.config.save_tokens(access_token, "", str(expires_at))

            self._update_headers()
        except requests.exceptions.RequestException as e:
            raise ClientError(f"Failed to obtain OAuth token: {e}")

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

    def _refresh_token(self):
        """Refresh the access token using the refresh token."""
        refresh_token = self.config.refresh_token
        if not refresh_token:
            raise ClientError(
                "No refresh token available. Run 'fedex auth login' to re-authenticate."
            )

        # TODO: Implement token refresh for your specific API
        # token_url = f"{self.base_url}/oauth/token"
        # response = requests.post(token_url, data={...})
        # self.config.save_tokens(new_access, new_refresh, expires_at)
        # self._update_headers()
        raise ClientError("Token refresh not implemented. Run 'fedex auth login'.")

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retry: bool = True,
    ) -> Dict:
        """
        Make an HTTP request to the Fedex API with exponential retry.

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

    def check_availability(
        self,
        street: str,
        city: str,
        state: str,
        postal_code: str,
        carrier: str = "FDXE",
        pickup_date: Optional[str] = None,
        package_ready_time: str = "15:30:00",
        close_time: str = "18:00:00",
        residential: bool = False,
    ) -> List[PickupAvailabilityOption]:
        """
        Check pickup availability for a given location.

        Args:
            street: Street address
            city: City name
            state: State or province code
            postal_code: Postal code
            carrier: Carrier code (FDXE=Express, FDXG=Ground)
            pickup_date: Date for pickup (YYYY-MM-DD), defaults to today
            package_ready_time: Time package will be ready (HH:MM:SS)
            close_time: Latest pickup time (HH:MM:SS)
            residential: Whether this is a residential address

        Returns:
            List of PickupAvailabilityOption models showing available times
        """
        endpoint = "/pickup/v1/pickups/availabilities"

        address = {
            "streetLines": [street],
            "city": city,
            "stateOrProvinceCode": state,
            "postalCode": postal_code,
            "countryCode": "US",
            "residential": residential,
        }

        pickup_request = {
            "pickupAddress": address,
            "dispatchDate": pickup_date,
            "packageReadyTime": package_ready_time,
            "customerCloseTime": close_time,
            "pickupType": "ON_CALL",
            "pickupRequestType": ["SAME_DAY", "FUTURE_DAY"],
            "shipmentAttributes": {
                "serviceType": "FEDEX_EXPRESS_SAVER" if carrier == "FDXE" else "FEDEX_GROUND",
                "packagingType": "YOUR_PACKAGING",
            },
            "carriers": [carrier],
            "countryRelationship": "DOMESTIC",
        }

        # Remove None values
        pickup_request = {k: v for k, v in pickup_request.items() if v is not None}

        response = self._make_request("POST", endpoint, data=pickup_request)

        # Extract availability options from response
        output = response.get("output", {})
        raw_options = output.get("options", [])

        return create_availability_options(raw_options)

    def schedule_pickup(
        self,
        account_number: str,
        street: str,
        city: str,
        state: str,
        postal_code: str,
        carrier: str = "FDXE",
        package_count: int = 1,
        package_weight: Optional[float] = None,
        weight_units: str = "LB",
        ready_time: str = "15:30:00",
        close_time: str = "18:00:00",
        remarks: Optional[str] = None,
        residential: bool = False,
        package_location: str = "FRONT",
        pickup_date: Optional[str] = None,
    ) -> Pickup:
        """
        Schedule a new pickup.

        Args:
            account_number: FedEx account number to bill
            street: Street address
            city: City name
            state: State or province code
            postal_code: Postal code
            carrier: Carrier code (FDXE=Express, FDXG=Ground)
            package_count: Number of packages
            package_weight: Total weight (optional)
            weight_units: Weight units (LB or KG)
            ready_time: Time package will be ready (HH:MM:SS)
            close_time: Latest pickup time (HH:MM:SS)
            remarks: Delivery instructions (max 60 chars)
            residential: Whether this is a residential address
            package_location: Where packages are located (FRONT, REAR, SIDE, NONE)
            pickup_date: Date for pickup (YYYY-MM-DD), defaults to today for Express, tomorrow for Ground

        Returns:
            Pickup model with confirmation code
        """
        endpoint = "/pickup/v1/pickups"

        # Determine pickup date and type
        from datetime import date, timedelta
        today = date.today()

        if pickup_date:
            scheduled_date = pickup_date
        elif carrier == "FDXG":
            # FedEx Ground requires next business day or later
            tomorrow = today + timedelta(days=1)
            # Skip weekend days
            while tomorrow.weekday() >= 5:  # 5=Saturday, 6=Sunday
                tomorrow += timedelta(days=1)
            scheduled_date = tomorrow.isoformat()
        else:
            # FedEx Express can do same day
            scheduled_date = today.isoformat()

        # Determine if this is same day or future day pickup
        pickup_date_type = "SAME_DAY" if scheduled_date == today.isoformat() else "FUTURE_DAY"

        address = {
            "streetLines": [street],
            "city": city,
            "stateOrProvinceCode": state,
            "postalCode": postal_code,
            "countryCode": "US",
            "residential": residential,
        }

        pickup_request = {
            "associatedAccountNumber": {"value": account_number},
            "originDetail": {
                "pickupAddressType": "ACCOUNT",
                "pickupLocation": {
                    "contact": {
                        "companyName": "Company",
                        "personName": "Pickup Contact",
                        "phoneNumber": "5555555555",
                    },
                    "address": address,
                },
                "readyDateTimestamp": f"{scheduled_date}T{ready_time}Z",
                "customerCloseTime": close_time,
                "pickupDateType": pickup_date_type,
                "packageLocation": package_location,
            },
            "carrierCode": carrier,
            "packageCount": package_count,
            "countryRelationships": "DOMESTIC",
            "pickupType": "ON_CALL",
            "remarks": remarks or "FedEx CLI scheduled pickup",
        }

        if package_weight:
            pickup_request["totalWeight"] = {
                "units": weight_units,
                "value": package_weight,
            }

        response = self._make_request("POST", endpoint, data=pickup_request)

        # Extract pickup from response output
        output = response.get("output", {})
        pickup_code = output.get("pickupConfirmationCode")
        location = output.get("location")

        return Pickup(
            pickup_confirmation_code=pickup_code,
            carrier=carrier,
            scheduled_date=scheduled_date,
            location=location,
        )

    def cancel_pickup(
        self,
        account_number: str,
        confirmation_code: str,
        scheduled_date: str,
        carrier: str = "FDXE",
        location: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Cancel a scheduled pickup.

        Args:
            account_number: FedEx account number
            confirmation_code: Pickup confirmation code
            scheduled_date: Scheduled pickup date (YYYY-MM-DD)
            carrier: Carrier code (FDXE or FDXG)
            location: Location code (required for Express)

        Returns:
            Cancellation response as dict
        """
        endpoint = "/pickup/v1/pickups/cancel"

        cancel_request = {
            "associatedAccountNumber": {"value": account_number},
            "pickupConfirmationCode": confirmation_code,
            "scheduledDate": scheduled_date,
            "carrierCode": carrier,
            "remarks": "Cancelled via FedEx CLI",
        }

        if location and carrier == "FDXE":
            cancel_request["location"] = location

        response = self._make_request("PUT", endpoint, data=cancel_request)

        output = response.get("output", {})
        return {
            "confirmation_code": output.get("pickupConfirmationCode"),
            "message": output.get("cancelConfirmationMessage", "Pickup cancelled"),
        }

    def _get_today(self) -> str:
        """Get today's date in YYYY-MM-DD format."""
        from datetime import date
        return date.today().isoformat()


# Module-level client instance - singleton pattern
_client: Optional[FedexClient] = None


def get_client() -> FedexClient:
    """Get or create the global Fedex client instance."""
    global _client
    if _client is None:
        _client = FedexClient()
    return _client
