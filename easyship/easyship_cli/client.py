"""Easyship Public API client."""
from typing import Any, Dict, List, Optional
import random
import time

import requests

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import parse_filter_string, validate_filters

from .config import get_config
from .models import Account, Courier, CourierDetail, create_account, create_courier, create_courier_detail

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

SUPPORTED_COURIER_FILTERS = {
    "country_alpha2",
    "customer_reference_id",
    "auth_state",
    "state",
    "umbrella_name",
    "active_courier_services",
    "easyship_courier",
}
ARRAY_FILTER_FIELDS = {"country_alpha2", "auth_state", "state"}


class EasyshipClient:
    """Client for Easyship Public API endpoints used by this CLI."""

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = get_config()
        if not self.config.personal_access_token:
            raise ClientError(
                "Missing credentials: PERSONAL_ACCESS_TOKEN. "
                "Run 'easyship auth login' to authenticate."
            )
        self.base_url = self.config.base_url.rstrip("/")
        self.headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.config.personal_access_token}",
        }
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_delay)
        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        delay += random.uniform(-jitter_range, jitter_range)
        return min(delay, self.max_delay)

    def _is_retryable(self, response: Optional[requests.Response], exception: Optional[Exception]) -> bool:
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
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return None
        try:
            return float(retry_after)
        except ValueError:
            return None

    def _extract_error_detail(self, response: requests.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:500] if response.text else "Unknown error"
        if isinstance(payload, dict):
            if "error" in payload:
                return str(payload["error"])
            if "message" in payload:
                return str(payload["message"])
        return str(payload)[:500]

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        url = f"{self.base_url}{endpoint}"
        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None

        for attempt in range(self.max_retries + 1):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    params=params,
                    timeout=30,
                )
                last_response = response
                if self._is_retryable(response, None) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt, self._get_retry_after(response)))
                    continue
                break
            except requests.exceptions.RequestException as exc:
                last_exception = exc
                if self._is_retryable(None, exc) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt))
                    continue
                break

        if last_exception is not None and last_response is None:
            raise ClientError(f"Request failed after retries: {last_exception}")
        if last_response is None:
            raise ClientError("Request failed: no response received")
        if last_response.status_code < 200 or last_response.status_code >= 300:
            raise ClientError(f"HTTP {last_response.status_code}: {self._extract_error_detail(last_response)}")
        return last_response.json()

    def _courier_params_from_filters(self, filters: Optional[List[str]]) -> Dict[str, Any]:
        if not filters:
            return {}
        validate_filters(filters)
        params: Dict[str, Any] = {}
        for filter_string in filters:
            for field, op, value in parse_filter_string(filter_string):
                if op != "eq":
                    raise ClientError(f"Unsupported filter operator for couriers: {field}:{op}")
                if field not in SUPPORTED_COURIER_FILTERS:
                    raise ClientError(f"Unsupported courier filter field: {field}")
                if value is None:
                    raise ClientError(f"Filter '{field}:{op}' requires a value")
                if field in ARRAY_FILTER_FIELDS:
                    params.setdefault(field, []).append(value)
                elif field in {"active_courier_services", "easyship_courier"}:
                    lowered = value.lower()
                    if lowered not in {"true", "false"}:
                        raise ClientError(f"Filter '{field}' expects true or false")
                    params[field] = lowered == "true"
                else:
                    params[field] = value
        return params

    @cached
    def get_account(self) -> Account:
        """Return the current authenticated account payload."""
        data = self._make_request("GET", "/account")
        if not isinstance(data, dict):
            raise ClientError("Expected account response to be an object.")
        return create_account(data)

    @cached
    def list_couriers(self, limit: int = 100, filters: Optional[List[str]] = None) -> List[Courier]:
        """List active couriers from Easyship."""
        if limit <= 0:
            raise ClientError("limit must be greater than 0")
        params = self._courier_params_from_filters(filters)
        page = 1
        remaining = limit
        couriers: List[Courier] = []

        while remaining > 0:
            page_size = min(remaining, 100)
            page_params = dict(params)
            page_params["page"] = page
            page_params["per_page"] = page_size
            payload = self._make_request("GET", "/couriers", params=page_params)
            if not isinstance(payload, dict) or "couriers" not in payload:
                raise ClientError("Expected courier list response to contain 'couriers'.")
            records = payload["couriers"]
            if not isinstance(records, list):
                raise ClientError("Expected 'couriers' to be a list.")
            for record in records:
                if not isinstance(record, dict):
                    raise ClientError("Expected each courier record to be an object.")
                couriers.append(create_courier(record))
            if len(records) < page_size:
                break
            remaining = limit - len(couriers)
            page += 1

        return couriers[:limit]

    @cached
    def get_courier(self, courier_id: str) -> CourierDetail:
        """Get a courier by its Easyship courier id."""
        payload = self._make_request("GET", f"/couriers/{courier_id}")
        if not isinstance(payload, dict):
            raise ClientError("Expected courier detail response to be an object.")
        return create_courier_detail(payload)


_client: Optional[EasyshipClient] = None


def get_client() -> EasyshipClient:
    """Return a process-global Easyship client."""
    global _client
    if _client is None:
        _client = EasyshipClient()
    return _client
