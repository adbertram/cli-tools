"""Awin Publisher API client.

Awin uses Bearer token authentication. Tokens are generated at
https://ui.awin.com/awin-api and are scoped to the user, granting access
to every publisher account the user belongs to.

Docs: https://help.awin.com/apidocs
"""
from typing import Any, List, Optional
import random
import time

import requests

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    parse_filter_string,
    validate_filters,
)

from .config import get_config
from .models import (
    Programme,
    Publisher,
    create_programme,
    create_publisher,
)


DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class AwinClient:
    """Client for the Awin Publisher API."""

    def __init__(
        self,
        config=None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = config or get_config()
        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'awin auth login' to authenticate."
            )

        self.base_url = self.config.base_url.rstrip("/")
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
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
        return min(delay + random.uniform(-jitter_range, jitter_range), self.max_delay)

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
            body = response.json()
            if isinstance(body, dict):
                if "error" in body:
                    err = body["error"]
                    if isinstance(err, dict):
                        return err.get("message") or err.get("description") or str(err)
                    return str(err)
                if "message" in body:
                    return str(body["message"])
            return str(body)[:500]
        except ValueError:
            return response.text[:500] if response.text else "Unknown error"

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        data: Optional[dict] = None,
    ) -> Any:
        if not endpoint.startswith("/"):
            raise ClientError("Awin endpoint must start with '/'")
        url = f"{self.base_url}{endpoint}"
        last_exception: Optional[requests.exceptions.RequestException] = None
        last_response: Optional[requests.Response] = None

        for attempt in range(self.max_retries + 1):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    params=params,
                    json=data,
                    timeout=30,
                )
                last_response = response
                if response.status_code in RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt, self._get_retry_after(response)))
                    continue
                break
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ) as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt))
                    continue
                break

        if last_response is None:
            raise ClientError(f"Request failed after {self.max_retries + 1} attempts: {last_exception}")
        if not last_response.ok:
            raise ClientError(
                f"HTTP {last_response.status_code}: {self._extract_error_detail(last_response)}"
            )
        if last_response.status_code == 204 or not last_response.content:
            return {}
        return last_response.json()

    # ---- Publishers ---------------------------------------------------------

    @cached
    def list_publishers(self, filters: Optional[List[str]] = None) -> List[Publisher]:
        """List publisher accounts accessible to the authenticated user.

        GET /accounts -- returns ``{"userId":..., "accounts":[...]}``. We
        filter to ``accountType == "publisher"`` to keep the model focused
        on publisher accounts. Pass ``accountType:eq:advertiser`` via
        ``--filter`` to see advertiser accounts on the same user.
        """
        body = self._request("GET", "/accounts")
        if not isinstance(body, dict) or "accounts" not in body:
            raise ClientError("Awin /accounts response missing 'accounts' array")
        accounts = body["accounts"]
        if not isinstance(accounts, list):
            raise ClientError("Awin /accounts 'accounts' field was not a list")
        if filters:
            validate_filters(filters)
            accounts = apply_filters(accounts, filters)
        else:
            accounts = [a for a in accounts if a.get("accountType") == "publisher"]
        return [create_publisher(item) for item in accounts]

    # ---- Programmes (joined advertiser programmes) --------------------------

    @cached
    def list_programmes(
        self,
        publisher_id: Optional[str] = None,
        relationship: str = "joined",
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[Programme]:
        """List advertiser programmes for a publisher.

        GET /publishers/{publisherId}/programmes?relationship=joined|notjoined|pending
        """
        pid = publisher_id or self.config.awin_publisher_id
        params: dict = {"relationship": relationship}

        if filters:
            validate_filters(filters)
            for filter_string in filters:
                for field, op, value in parse_filter_string(filter_string):
                    if op != "eq":
                        raise FilterValidationError(
                            f"Unsupported Awin filter '{field}:{op}'. Awin filters use equality."
                        )
                    params[field] = value

        body = self._request("GET", f"/publishers/{pid}/programmes", params=params)
        if not isinstance(body, list):
            raise ClientError("Awin /programmes response was not an array")
        return [create_programme(item) for item in body[:limit]]

    def get_programme(self, publisher_id: Optional[str], programme_id: str) -> Programme:
        """Get one programme by id.

        GET /publishers/{publisherId}/programmedetails?advertiserId={programme_id}
        """
        pid = publisher_id or self.config.awin_publisher_id
        body = self._request(
            "GET",
            f"/publishers/{pid}/programmedetails",
            params={"advertiserId": programme_id, "relationship": "joined"},
        )
        if isinstance(body, dict) and "programmeInfo" in body:
            return create_programme(body["programmeInfo"])
        return create_programme(body)


_client: Optional[AwinClient] = None


def get_client() -> AwinClient:
    global _client
    if _client is None:
        _client = AwinClient()
    return _client
