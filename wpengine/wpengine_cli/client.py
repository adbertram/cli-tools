"""WP Engine Hosting Platform API client."""

from __future__ import annotations

import random
import time
from typing import Any, Optional

import requests
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import apply_filters, parse_filter_string, validate_filters

from .config import get_config

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
REQUEST_TIMEOUT = 30
API_PAGE_LIMIT = 100
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class WpengineClient:
    """Client for the WP Engine Hosting Platform API."""

    def __init__(
        self,
        config=None,
        *,
        session=None,
        require_auth: bool = True,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = config or get_config()
        self.session = session or requests
        self.base_url = self.config.base_url.rstrip("/")
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.headers = {"Accept": "application/json", "Content-Type": "application/json"}
        self.auth = self._build_auth(require_auth=not not require_auth)

    def _build_auth(self, *, require_auth: bool) -> Optional[tuple[str, str]]:
        username = self.config.username
        password = self.config.password
        if username and password:
            return (username, password)
        if require_auth:
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'wpengine auth login' to authenticate with your WP Engine API User ID and API Password."
            )
        return None

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
        return response is not None and response.status_code in RETRYABLE_STATUS_CODES

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
            if "message" in body:
                return str(body["message"])
            if "errors" in body:
                return str(body["errors"])
        return str(body)[:500]

    def _make_request(
        self,
        method: str,
        endpoint: str,
        *,
        data: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        retry: bool = True,
        auth_required: bool = True,
    ) -> Any:
        url = f"{self.base_url}{endpoint}"
        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None
        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    auth=self.auth if auth_required else None,
                    json=data,
                    params=params,
                    timeout=REQUEST_TIMEOUT,
                )
                last_response = response
                if retry and self._is_retryable(response, None) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt, self._get_retry_after(response)))
                    continue
                break
            except requests.exceptions.RequestException as exc:
                last_exception = exc
                if retry and self._is_retryable(None, exc) and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt))
                    continue
                break

        if last_exception is not None and last_response is None:
            raise ClientError(f"Request failed after {attempt + 1} attempts: {last_exception}")
        if last_response is None:
            raise ClientError("Request failed: no response received")
        if not last_response.ok:
            raise ClientError(f"HTTP {last_response.status_code}: {self._extract_error_detail(last_response)}")
        if last_response.status_code == 204:
            return {}
        if not getattr(last_response, "content", b""):
            return {}
        try:
            return last_response.json()
        except ValueError as exc:
            raise ClientError(f"HTTP {last_response.status_code}: response was not valid JSON") from exc

    def _api_params_for_filters(
        self,
        filters: Optional[list[str]],
        *,
        server_fields: set[str],
    ) -> tuple[dict[str, str], list[str]]:
        if not filters:
            return {}, []
        validate_filters(filters)
        api_params: dict[str, str] = {}
        client_filters: list[str] = []
        for filter_string in filters:
            client_conditions: list[str] = []
            for field, op, value in parse_filter_string(filter_string):
                if field in server_fields and op == "eq" and value is not None:
                    api_params[field] = value
                else:
                    if value is None:
                        client_conditions.append(f"{field}:{op}")
                    else:
                        client_conditions.append(f"{field}:{op}:{value}")
            if client_conditions:
                client_filters.append(",".join(client_conditions))
        return api_params, client_filters

    def _paginated_results(
        self,
        endpoint: str,
        *,
        limit: int,
        filters: Optional[list[str]] = None,
        server_filter_fields: Optional[set[str]] = None,
    ) -> list[dict[str, Any]]:
        if limit < 1:
            raise ClientError("--limit must be greater than zero.")

        api_params, client_filters = self._api_params_for_filters(
            filters,
            server_fields=server_filter_fields or set(),
        )
        rows: list[dict[str, Any]] = []
        offset = 0

        while len(rows) < limit:
            page_limit = min(API_PAGE_LIMIT, limit - len(rows))
            params = {**api_params, "limit": page_limit, "offset": offset}
            payload = self._make_request("GET", endpoint, params=params)
            if isinstance(payload, list):
                page_rows = payload
                has_next = len(page_rows) == page_limit
            elif isinstance(payload, dict) and isinstance(payload.get("results"), list):
                page_rows = payload["results"]
                has_next = bool(payload.get("next"))
            else:
                raise ClientError(f"Expected list response from {endpoint}, got {type(payload).__name__}.")

            rows.extend(page_rows)
            if len(rows) >= limit or not has_next or not page_rows:
                break
            offset += len(page_rows)

        if client_filters:
            rows = apply_filters(rows, client_filters)
        return rows[:limit]

    def get_api_status(self) -> dict[str, Any]:
        """Return the public Hosting Platform API status."""
        payload = self._make_request("GET", "/status", auth_required=False)
        if not isinstance(payload, dict):
            raise ClientError("Expected object response from /status.")
        return payload

    @cached
    def list_accounts(self, limit: int = 100, filters: Optional[list[str]] = None) -> list[dict[str, Any]]:
        """List WP Engine accounts."""
        return self._paginated_results("/accounts", limit=limit, filters=filters)

    @cached
    def get_account(self, account_id: str) -> dict[str, Any]:
        """Get a WP Engine account by ID."""
        payload = self._make_request("GET", f"/accounts/{account_id}")
        if not isinstance(payload, dict):
            raise ClientError("Expected account object response.")
        return payload

    @cached
    def list_sites(self, limit: int = 100, filters: Optional[list[str]] = None) -> list[dict[str, Any]]:
        """List WP Engine sites."""
        return self._paginated_results(
            "/sites",
            limit=limit,
            filters=filters,
            server_filter_fields={"account_id"},
        )

    @cached
    def get_site(self, site_id: str) -> dict[str, Any]:
        """Get a WP Engine site by ID."""
        payload = self._make_request("GET", f"/sites/{site_id}")
        if not isinstance(payload, dict):
            raise ClientError("Expected site object response.")
        return payload

    @cached
    def list_environments(self, limit: int = 100, filters: Optional[list[str]] = None) -> list[dict[str, Any]]:
        """List WP Engine environments, documented by the API as installs."""
        return self._paginated_results(
            "/installs",
            limit=limit,
            filters=filters,
            server_filter_fields={"account_id"},
        )

    @cached
    def get_environment(self, environment_id: str) -> dict[str, Any]:
        """Get a WP Engine environment by install ID."""
        payload = self._make_request("GET", f"/installs/{environment_id}")
        if not isinstance(payload, dict):
            raise ClientError("Expected environment object response.")
        return payload

    def purge_cache(self, environment_id: str, cache_type: str) -> dict[str, Any]:
        """Purge an environment cache."""
        payload = self._make_request(
            "POST",
            f"/installs/{environment_id}/purge_cache",
            data={"type": cache_type},
            retry=False,
        )
        if isinstance(payload, dict) and payload:
            return payload
        return {"accepted": True, "environment_id": environment_id, "type": cache_type}

    @cached
    def list_ssh_keys(self, limit: int = 100, filters: Optional[list[str]] = None) -> list[dict[str, Any]]:
        """List SSH keys attached to the authenticated WP Engine user."""
        return self._paginated_results("/ssh_keys", limit=limit, filters=filters)

    def get_ssh_key(self, ssh_key_id: str) -> dict[str, Any]:
        """Get one SSH key by searching the documented SSH key list endpoint."""
        offset = 0
        while True:
            payload = self._make_request(
                "GET",
                "/ssh_keys",
                params={"limit": API_PAGE_LIMIT, "offset": offset},
            )
            if isinstance(payload, dict) and isinstance(payload.get("results"), list):
                page_rows = payload["results"]
                has_next = bool(payload.get("next"))
            elif isinstance(payload, list):
                page_rows = payload
                has_next = len(page_rows) == API_PAGE_LIMIT
            else:
                raise ClientError("Expected SSH key list response.")

            for key in page_rows:
                if not isinstance(key, dict):
                    continue
                key_ids = {str(value) for value in (key.get("id"), key.get("uuid")) if value is not None}
                if ssh_key_id in key_ids:
                    return key

            if not page_rows or not has_next:
                break
            offset += len(page_rows)

        raise ClientError(f"SSH key not found: {ssh_key_id}")

    def add_ssh_key(self, public_key: str) -> dict[str, Any]:
        """Add an SSH public key to WP Engine."""
        payload = self._make_request("POST", "/ssh_keys", data={"public_key": public_key}, retry=False)
        if not isinstance(payload, dict):
            raise ClientError("Expected SSH key object response.")
        return payload

    def delete_ssh_key(self, ssh_key_id: str) -> dict[str, Any]:
        """Delete an SSH key from WP Engine."""
        self._make_request("DELETE", f"/ssh_keys/{ssh_key_id}", retry=False)
        return {"deleted": True, "ssh_key_id": ssh_key_id}


_client: Optional[WpengineClient] = None


def get_client() -> WpengineClient:
    """Get or create the global WP Engine client instance."""
    global _client
    if _client is None:
        _client = WpengineClient()
    return _client
