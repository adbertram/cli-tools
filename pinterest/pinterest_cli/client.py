"""Pinterest API client."""

from __future__ import annotations

import random
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
from requests.exceptions import ChunkedEncodingError, ConnectionError, RequestException, Timeout

from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filter_map import FilterMap
from cli_tools_shared.filters import apply_filters, apply_limit, parse_filter_string, validate_filters
from cli_tools_shared.token_manager import TokenManager

from .config import Config, get_config
from .models import Board, Pin, UserAccount

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
MAX_PAGE_SIZE = 250
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

activity = get_activity_logger("pinterest")


class PinterestClient:
    """Client for Pinterest API v5."""

    def __init__(
        self,
        config: Optional[Config] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = config or get_config()
        if not self.config.access_token:
            raise ClientError("Missing ACCESS_TOKEN. Run 'pinterest auth login' to authenticate.")

        self.base_url = self.config.base_url.rstrip("/")
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.tokens = TokenManager(self.config, on_refresh=self._update_headers)
        self._update_headers()

        self._board_filter_map = FilterMap().register_api_translator(
            "privacy",
            lambda op, value: {"privacy": value} if op == "eq" else {},
        )

    def _update_headers(self) -> None:
        """Update HTTP headers from the current config state."""
        self.headers = {
            "Authorization": f"Bearer {self.config.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """Calculate exponential-backoff retry delay with jitter."""
        if retry_after is not None:
            return min(retry_after, self.max_delay)

        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        delay += random.uniform(-jitter_range, jitter_range)
        return min(delay, self.max_delay)

    def _get_retry_after(self, response: requests.Response) -> Optional[float]:
        """Return Retry-After in seconds when present."""
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return None
        return float(retry_after)

    def _extract_error_message(self, response: requests.Response) -> str:
        """Extract Pinterest API error details from a response."""
        try:
            payload = response.json()
        except ValueError:
            return response.text or f"HTTP {response.status_code}"

        if isinstance(payload, dict):
            message = payload.get("message") or payload.get("error_description")
            if message:
                return str(message)
        return str(payload)

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        retry: bool = True,
    ) -> Dict[str, Any]:
        """Make an authenticated request to Pinterest API v5."""
        url = f"{self.base_url}{endpoint}"
        max_attempts = self.max_retries + 1 if retry else 1
        last_error: Optional[Exception] = None

        self.tokens.ensure_valid()

        for attempt in range(max_attempts):
            try:
                activity.info("HTTP %s %s params=%s", method, endpoint, params)
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    params=params,
                    json=data,
                    timeout=30,
                )

                if response.status_code == 401:
                    activity.info("Refreshing expired token after 401 from %s", endpoint)
                    self.tokens.force_refresh()
                    response = requests.request(
                        method=method,
                        url=url,
                        headers=self.headers,
                        params=params,
                        json=data,
                        timeout=30,
                    )

                if response.status_code in RETRYABLE_STATUS_CODES and attempt < max_attempts - 1:
                    delay = self._calculate_retry_delay(attempt, self._get_retry_after(response))
                    activity.info(
                        "Retrying %s %s after status %s in %.2fs",
                        method,
                        endpoint,
                        response.status_code,
                        delay,
                    )
                    time.sleep(delay)
                    continue

                if not response.ok:
                    raise ClientError(
                        f"Pinterest API request failed: {response.status_code} - "
                        f"{self._extract_error_message(response)}"
                    )

                if not response.content:
                    return {}
                return response.json()

            except (ConnectionError, Timeout, ChunkedEncodingError) as error:
                last_error = error
                if attempt < max_attempts - 1:
                    delay = self._calculate_retry_delay(attempt)
                    activity.info(
                        "Retrying %s %s after %s in %.2fs",
                        method,
                        endpoint,
                        type(error).__name__,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                raise ClientError(f"Request failed: {error}") from error
            except RequestException as error:
                raise ClientError(f"Request failed: {error}") from error

        raise ClientError(f"Request failed: {last_error}")

    def _partition_filters(
        self,
        filters: List[str],
        api_fields: Dict[str, tuple[str, ...]],
    ) -> Tuple[List[str], List[str]]:
        """Split filters into API-supported and client-side groups."""
        server_filters: List[str] = []
        client_filters: List[str] = []

        for filter_string in filters:
            conditions = parse_filter_string(filter_string)
            if all(field in api_fields and op in api_fields[field] for field, op, _ in conditions):
                server_filters.append(filter_string)
            else:
                client_filters.append(filter_string)

        return server_filters, client_filters

    def _paginate_items(
        self,
        endpoint: str,
        *,
        limit: int,
        params: Optional[Dict[str, Any]],
        filters: Optional[List[str]],
        item_factory: Callable[[Dict[str, Any]], Any],
        api_filter_map: Optional[FilterMap] = None,
        api_filter_fields: Optional[Dict[str, tuple[str, ...]]] = None,
    ) -> List[Any]:
        """Fetch a paginated Pinterest list response and return typed items."""
        validated_filters = validate_filters(filters or [])
        request_params = dict(params or {})
        server_filters: List[str] = []
        client_filters = validated_filters

        if api_filter_map is not None and api_filter_fields is not None:
            server_filters, client_filters = self._partition_filters(validated_filters, api_filter_fields)
            if server_filters:
                request_params.update(api_filter_map.to_api_params(server_filters))

        collected: List[Dict[str, Any]] = []
        bookmark: Optional[str] = None
        page_size = min(limit, MAX_PAGE_SIZE)

        while True:
            page_params = dict(request_params)
            page_params["page_size"] = page_size
            if bookmark:
                page_params["bookmark"] = bookmark

            response = self._request("GET", endpoint, params=page_params)
            items = response.get("items", [])
            if not isinstance(items, list):
                raise ClientError(f"Unexpected response shape from {endpoint}: expected 'items' list")

            collected.extend(items)

            filtered = apply_filters(collected, client_filters) if client_filters else collected
            if len(filtered) >= limit:
                return [item_factory(item) for item in apply_limit(filtered, limit)]

            bookmark = response.get("bookmark")
            if not bookmark or not items:
                break

        filtered = apply_filters(collected, client_filters) if client_filters else collected
        return [item_factory(item) for item in apply_limit(filtered, limit)]

    def get_user_account(self, ad_account_id: Optional[str] = None) -> UserAccount:
        """Get the authenticated user's Pinterest account."""
        params = {"ad_account_id": ad_account_id} if ad_account_id else None
        response = self._request("GET", "/user_account", params=params)
        return UserAccount(**response)

    def list_boards(
        self,
        *,
        limit: int = 25,
        filters: Optional[List[str]] = None,
        ad_account_id: Optional[str] = None,
    ) -> List[Board]:
        """List Pinterest boards."""
        params = {"ad_account_id": ad_account_id} if ad_account_id else None
        return self._paginate_items(
            "/boards",
            limit=limit,
            params=params,
            filters=filters,
            item_factory=lambda item: Board(**item),
            api_filter_map=self._board_filter_map,
            api_filter_fields={"privacy": ("eq",)},
        )

    def get_board(self, board_id: str, ad_account_id: Optional[str] = None) -> Board:
        """Get a Pinterest board by ID."""
        params = {"ad_account_id": ad_account_id} if ad_account_id else None
        response = self._request("GET", f"/boards/{board_id}", params=params)
        return Board(**response)

    def list_pins(
        self,
        *,
        limit: int = 25,
        filters: Optional[List[str]] = None,
        ad_account_id: Optional[str] = None,
    ) -> List[Pin]:
        """List Pinterest pins."""
        params = {"ad_account_id": ad_account_id} if ad_account_id else None
        return self._paginate_items(
            "/pins",
            limit=limit,
            params=params,
            filters=filters,
            item_factory=lambda item: Pin(**item),
        )

    def get_pin(self, pin_id: str, ad_account_id: Optional[str] = None) -> Pin:
        """Get a Pinterest pin by ID."""
        params = {"ad_account_id": ad_account_id} if ad_account_id else None
        response = self._request("GET", f"/pins/{pin_id}", params=params)
        return Pin(**response)


_clients: Dict[str, PinterestClient] = {}


def get_client(config: Optional[Config] = None) -> PinterestClient:
    """Get or create a Pinterest client instance."""
    if config is not None:
        return PinterestClient(config=config)

    profile_name = get_config().get_active_profile_name()
    if profile_name not in _clients:
        _clients[profile_name] = PinterestClient()
    return _clients[profile_name]
