"""UPS Pickup API client."""

from __future__ import annotations

import base64
import random
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import requests
from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import print_success

from .config import get_config

activity = get_activity_logger("ups")

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _compact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: v for k, v in ((key, _compact(val)) for key, val in value.items()) if v not in (None, "", [], {})}
    if isinstance(value, list):
        return [item for item in (_compact(item) for item in value) if item not in (None, "", [], {})]
    return value


def _parse_time(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise ClientError("Time value cannot be empty")
    if ":" in cleaned:
        parts = cleaned.split(":")
        if len(parts) < 2:
            raise ClientError(f"Invalid time {value!r}; use HHMM, HH:MM, or HH:MM:SS")
        cleaned = f"{int(parts[0]):02d}{int(parts[1]):02d}"
    elif len(cleaned) in (3, 4) and cleaned.isdigit():
        cleaned = cleaned.zfill(4)
    else:
        raise ClientError(f"Invalid time {value!r}; use HHMM, HH:MM, or HH:MM:SS")

    hour = int(cleaned[:2])
    minute = int(cleaned[2:])
    if hour > 23 or minute > 59:
        raise ClientError(f"Invalid time {value!r}; hour must be 0-23 and minute 0-59")
    return cleaned


def _parse_date(value: Optional[str]) -> str:
    if not value:
        target = date.today()
        if target.weekday() >= 5:
            while target.weekday() >= 5:
                target += timedelta(days=1)
        return target.strftime("%Y%m%d")
    cleaned = value.strip()
    if len(cleaned) == 8 and cleaned.isdigit():
        datetime.strptime(cleaned, "%Y%m%d")
        return cleaned
    try:
        return datetime.strptime(cleaned, "%Y-%m-%d").strftime("%Y%m%d")
    except ValueError as exc:
        raise ClientError(f"Invalid pickup date {value!r}; use YYYY-MM-DD or YYYYMMDD") from exc


def _display_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


def _response_status(payload: dict) -> dict:
    response = payload.get("Response") if isinstance(payload, dict) else None
    if not isinstance(response, dict):
        return {}
    status = response.get("ResponseStatus")
    return status if isinstance(status, dict) else {}


def normalize_pickup_creation(response: dict) -> dict:
    """Preserve the UPS creation response while adding stable convenience fields."""
    payload = response.get("PickupCreationResponse", response)
    if not isinstance(payload, dict):
        return {"raw": payload}
    status = _response_status(payload)
    record = dict(payload)
    record.update(
        {
            "response_type": "PickupCreationResponse",
            "prn": payload.get("PRN"),
            "status_code": status.get("Code"),
            "status_description": status.get("Description"),
            "rate_status_code": (payload.get("RateStatus") or {}).get("Code")
            if isinstance(payload.get("RateStatus"), dict)
            else None,
            "rate_status_description": (payload.get("RateStatus") or {}).get("Description")
            if isinstance(payload.get("RateStatus"), dict)
            else None,
        }
    )
    return record


def normalize_pending_status(response: dict) -> List[dict]:
    """Return pending pickup rows while preserving UPS fields."""
    root = response.get("PickupPendingStatusResponse", response)
    if not isinstance(root, dict):
        return []
    pending = root.get("PendingStatus")
    if not pending:
        return []
    pending_rows = pending if isinstance(pending, list) else [pending]
    rows = []
    status = _response_status(root)
    for item in pending_rows:
        if not isinstance(item, dict):
            continue
        record = dict(item)
        record.update(
            {
                "response_type": "PickupPendingStatusResponse",
                "prn": item.get("PRN"),
                "service_date": _display_date(item.get("ServiceDate")),
                "pickup_type": item.get("PickupType"),
                "status_code": item.get("OnCallStatusCode") or status.get("Code"),
                "status_message": item.get("PickupStatusMessage") or status.get("Description"),
                "contact_name": item.get("ContactName"),
                "reference_number": item.get("ReferenceNumber"),
            }
        )
        rows.append(record)
    return rows


def build_pickup_payload(
    *,
    account_number: str,
    account_country: str,
    pickup_date: Optional[str],
    ready_time: str,
    close_time: str,
    company_name: str,
    contact_name: str,
    street: str,
    city: str,
    state: str,
    postal_code: str,
    country: str,
    phone: str,
    residential: bool,
    pickup_point: str,
    package_count: int,
    weight: float,
    weight_unit: str,
    service_code: str,
    container_code: str,
    destination_country: str,
    payment_method: str,
    special_instruction: Optional[str],
    reference_number: Optional[str],
    rate_pickup: bool,
    phone_extension: Optional[str] = None,
) -> dict:
    if package_count < 1:
        raise ClientError("Package count must be at least 1")
    if weight <= 0:
        raise ClientError("Weight must be greater than 0")

    payload = {
        "PickupCreationRequest": {
            "RatePickupIndicator": "Y" if rate_pickup else "N",
            "Shipper": {
                "Account": {
                    "AccountNumber": account_number,
                    "AccountCountryCode": account_country,
                }
            },
            "PickupDateInfo": {
                "CloseTime": _parse_time(close_time),
                "ReadyTime": _parse_time(ready_time),
                "PickupDate": _parse_date(pickup_date),
            },
            "PickupAddress": {
                "CompanyName": company_name,
                "ContactName": contact_name,
                "AddressLine": street,
                "City": city,
                "StateProvince": state,
                "PostalCode": postal_code,
                "CountryCode": country,
                "ResidentialIndicator": "Y" if residential else "N",
                "PickupPoint": pickup_point,
                "Phone": {
                    "Number": phone,
                    "Extension": phone_extension,
                },
                "AlternateAddressIndicator": "Y",
            },
            "PickupPiece": [
                {
                    "ServiceCode": service_code,
                    "Quantity": str(package_count),
                    "DestinationCountryCode": destination_country,
                    "ContainerCode": container_code,
                }
            ],
            "TotalWeight": {
                "Weight": str(weight),
                "UnitOfMeasurement": weight_unit,
            },
            "OverweightIndicator": "N",
            "PaymentMethod": payment_method,
            "SpecialInstruction": special_instruction,
            "ReferenceNumber": reference_number,
        }
    }
    return _compact(payload)


def ups_oauth_login(config, force: bool) -> None:
    """Login handler for UPS OAuth client-credentials flow."""
    client = UpsClient(config=config, require_auth=False)
    token = client.obtain_access_token()
    print_success(f"UPS access token saved; expires in {token.get('expires_in', 'unknown')} seconds")


class UpsClient:
    """Client for interacting with the UPS Pickup API."""

    def __init__(
        self,
        config=None,
        require_auth: bool = True,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = config or get_config()
        self.base_url = self.config.base_url.rstrip("/")
        self.token_base_url = self.config.token_base_url.rstrip("/")
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. Run 'ups auth login' to authenticate."
            )

        if require_auth and (not self.config.access_token or self._is_token_expired()):
            self.obtain_access_token()
        self._update_headers()

    def _update_headers(self) -> None:
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "transactionSrc": self.config.transaction_src,
        }
        if self.config.access_token:
            self.headers["Authorization"] = f"Bearer {self.config.access_token}"

    def _is_token_expired(self) -> bool:
        expires_at = self.config.token_expires_at
        if not expires_at:
            return True
        try:
            return time.time() > (float(expires_at) - 300)
        except (TypeError, ValueError):
            return True

    def obtain_access_token(self) -> dict:
        """Exchange UPS client ID/secret for an OAuth access token."""
        if not self.config.client_id or not self.config.client_secret:
            raise ClientError("CLIENT_ID and CLIENT_SECRET are required. Run 'ups auth login'.")

        token_url = f"{self.token_base_url}/security/v1/oauth/token"
        encoded = base64.b64encode(f"{self.config.client_id}:{self.config.client_secret}".encode()).decode()
        headers = {
            "Accept": "application/json",
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
            "x-merchant-id": self.config.client_id,
        }
        activity.info("Requesting UPS OAuth token")
        try:
            response = requests.post(
                token_url,
                data={"grant_type": "client_credentials"},
                headers=headers,
                timeout=30,
            )
        except requests.exceptions.RequestException as exc:
            activity.error("UPS OAuth token request failed: %s", exc)
            raise ClientError(f"Failed to obtain UPS OAuth token: {exc}") from exc

        if not response.ok:
            raise ClientError(f"UPS OAuth token request failed ({response.status_code}): {self._extract_error_detail(response)}")

        token_data = response.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise ClientError("UPS OAuth token response did not include access_token")
        expires_in = int(token_data.get("expires_in") or 3600)
        expires_at = str(time.time() + (expires_in * 0.9))
        self.config.save_tokens(access_token, None, expires_at)
        self._update_headers()
        activity.info("UPS OAuth token saved")
        return token_data

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
        return bool(response is not None and response.status_code in RETRYABLE_STATUS_CODES)

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
        if isinstance(body, dict):
            errors = body.get("response", {}).get("errors") if isinstance(body.get("response"), dict) else None
            if isinstance(errors, list) and errors:
                first = errors[0]
                if isinstance(first, dict):
                    code = first.get("code")
                    message = first.get("message")
                    return f"{code}: {message}" if code and message else str(first)
            if "message" in body:
                return str(body["message"])
            if "error_description" in body:
                return str(body["error_description"])
        return str(body)[:500]

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        retry: bool = True,
    ) -> Dict:
        if self._is_token_expired():
            self.obtain_access_token()

        url = f"{self.base_url}{endpoint}"
        request_headers = dict(self.headers)
        request_headers["transId"] = uuid.uuid4().hex[:32]
        if headers:
            request_headers.update(headers)

        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None
        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                activity.info("%s %s", method.upper(), endpoint)
                response = requests.request(
                    method=method,
                    url=url,
                    headers=request_headers,
                    json=data,
                    params=params,
                    timeout=30,
                )
                last_response = response
                activity.info("%s %s -> %s", method.upper(), endpoint, response.status_code)
                if retry and self._is_retryable(response, None) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt, self._get_retry_after(response)))
                    continue
                break
            except requests.exceptions.RequestException as exc:
                last_exception = exc
                activity.warning("%s %s failed on attempt %s: %s", method.upper(), endpoint, attempt + 1, exc)
                if retry and self._is_retryable(None, exc) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt))
                    continue
                break

        if last_exception is not None and last_response is None:
            raise ClientError(f"Request failed after {attempt + 1} attempts: {last_exception}")
        if last_response is None:
            raise ClientError("Request failed: no response received")
        if not last_response.ok:
            raise ClientError(f"UPS API request failed ({last_response.status_code}): {self._extract_error_detail(last_response)}")
        if last_response.status_code == 204:
            return {}
        return last_response.json()

    def test_auth(self) -> dict:
        token = self.obtain_access_token()
        return {"api_test": "passed", "token_type": token.get("token_type"), "base_url": self.base_url}

    def schedule_pickup(self, payload: dict, version: Optional[str] = None) -> dict:
        version = version or self.config.api_version
        response = self._make_request("POST", f"/pickupcreation/{version}/pickup", data=payload, retry=False)
        return normalize_pickup_creation(response)

    @cached
    def list_pickups(
        self,
        account_number: str,
        pickup_type: str = "oncall",
        version: Optional[str] = None,
    ) -> List[dict]:
        version = version or self.config.api_version
        response = self._make_request(
            "GET",
            f"/shipments/{version}/pickup/{pickup_type}",
            headers={"AccountNumber": account_number},
        )
        return normalize_pending_status(response)

    @cached
    def get_pickup(
        self,
        prn: str,
        account_number: str,
        pickup_type: str = "oncall",
        version: Optional[str] = None,
    ) -> dict:
        rows = self.list_pickups(account_number=account_number, pickup_type=pickup_type, version=version)
        for row in rows:
            if row.get("prn") == prn or row.get("PRN") == prn:
                return row
        raise ClientError(f"Pickup {prn} was not found in pending UPS pickups for account {account_number}.")


_client: Optional[UpsClient] = None


def get_client() -> UpsClient:
    """Get or create the global UPS client instance."""
    global _client
    if _client is None:
        _client = UpsClient()
    return _client
