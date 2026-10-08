"""Dataforseo API client."""

import random
import time
from typing import Dict, List, Optional

import requests
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError, CredentialError
from cli_tools_shared.filters import parse_filter_part, split_filter_parts, validate_filters

from .config import get_config

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
DEFAULT_TIMEOUT = 60.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


DEFAULT_LOCATION_CODE = 2840  # United States
DEFAULT_LANGUAGE_CODE = "en"
STATUS_OK = 20000
MAX_FILTER_CONDITIONS = 8
MAX_IDEAS_LIMIT = 1000

# CLI filter operator -> DataForSEO Labs filter operator.
_OPERATOR_MAP = {
    "eq": "=",
    "ne": "<>",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "in": "in",
    "nin": "not_in",
    "like": "like",
    "ilike": "ilike",
}
# Operators that become an ilike pattern: (prefix, suffix) wrapped around the value.
_PATTERN_OPERATORS = {"contains": ("%", "%"), "startswith": ("", "%"), "endswith": ("%", "")}


def _require_keywords(keywords: List[str]) -> None:
    if not keywords or any(not keyword.strip() for keyword in keywords):
        raise ClientError("Keywords must be non-empty strings")


def _typed(value: str):
    """Return int/float for numeric strings (DataForSEO compares numbers numerically)."""
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            continue
    return value


def to_api_filters(filters: Optional[List[str]]) -> Optional[list]:
    """Translate CLI ``field:op:value`` filters into a DataForSEO Labs ``filters`` array.

    Conditions inside one ``--filter`` (comma separated) are ANDed. More than one
    ``--filter`` flag means OR in the cli-tools syntax, which this API path cannot
    express in a single request, so it is rejected instead of silently ANDed.
    """
    if not filters:
        return None
    if len(filters) > 1:
        raise ClientError(
            "Multiple --filter flags mean OR in cli-tools syntax and DataForSEO filters here "
            "only support AND. Join conditions with commas in one --filter, "
            "e.g. --filter 'keyword_info.search_volume:gte:100,keyword_properties.keyword_difficulty:lt:40'."
        )
    validate_filters(filters)
    conditions = []
    for part in split_filter_parts(filters[0]):
        part = part.strip()
        if not part:
            continue
        field, op, value = parse_filter_part(part)
        if op in _OPERATOR_MAP:
            api_op = _OPERATOR_MAP[op]
            if op in ("in", "nin"):
                api_value = [_typed(v) for v in value.split("|")]
            elif op in ("like", "ilike"):
                api_value = value
            else:
                api_value = _typed(value)
        elif op in _PATTERN_OPERATORS:
            prefix, suffix = _PATTERN_OPERATORS[op]
            api_op, api_value = "ilike", f"{prefix}{value}{suffix}"
        else:
            supported = ", ".join(sorted([*_OPERATOR_MAP, *_PATTERN_OPERATORS]))
            raise ClientError(f"Filter operator '{op}' is not supported by DataForSEO. Supported: {supported}")
        conditions.append([field, api_op, api_value])
    if len(conditions) > MAX_FILTER_CONDITIONS:
        raise ClientError(f"DataForSEO allows at most {MAX_FILTER_CONDITIONS} filter conditions, got {len(conditions)}")
    api_filters: list = []
    for condition in conditions:
        if api_filters:
            api_filters.append("and")
        api_filters.append(condition)
    return api_filters


class DataforseoClient:
    """Client for interacting with Dataforseo API."""

    def __init__(
        self,
        config=None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.config = config or get_config()
        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise CredentialError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'dataforseo auth login' to authenticate."
            )
        self.base_url = self.config.base_url
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.timeout = timeout
        self.last_cost: Optional[float] = None
        self._update_headers()

    def _update_headers(self):
        self.headers = {"Accept": "application/json", "Content-Type": "application/json"}
        self.auth = (self.config.username, self.config.password)

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
        if response is not None:
            return response.status_code in RETRYABLE_STATUS_CODES
        return False

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
        if isinstance(body, dict) and "status_message" in body:
            return f"{body.get('status_code')} {body['status_message']}"
        return str(body)[:500]

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[list] = None,
        params: Optional[Dict] = None,
        retry: bool = True,
    ) -> Dict:
        url = f"{self.base_url}{endpoint}"
        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None
        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                response = requests.request(method, url, headers=self.headers, auth=self.auth, json=data, params=params, timeout=self.timeout)
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
        if last_response.status_code == 401:
            raise CredentialError(
                f"HTTP {last_response.status_code}: {self._extract_error_detail(last_response)}. "
                "Run 'dataforseo auth login --force' with the API login and API password."
            )
        if not last_response.ok:
            raise ClientError(f"HTTP {last_response.status_code}: {self._extract_error_detail(last_response)}")
        return self._check_envelope(last_response.json())

    def _check_envelope(self, body: Dict) -> Dict:
        """Fail on any non-20000 status (top level or task level) and record the call cost."""
        if body.get("status_code") != STATUS_OK:
            raise ClientError(f"DataForSEO error {body.get('status_code')}: {body.get('status_message')}")
        for task in body.get("tasks") or []:
            if task.get("status_code") != STATUS_OK:
                raise ClientError(f"DataForSEO task error {task.get('status_code')}: {task.get('status_message')}")
        self.last_cost = body.get("cost")
        return body

    def _task_result(self, body: Dict) -> List[dict]:
        """Return tasks[0].result (this CLI always sends exactly one task)."""
        tasks = body.get("tasks") or []
        if len(tasks) != 1:
            raise ClientError(f"Expected exactly one DataForSEO task, got {len(tasks)}")
        return tasks[0].get("result") or []

    def get_user_data(self) -> dict:
        """Account data (login, money.balance, rate limits, prices). Free endpoint."""
        result = self._task_result(self._make_request("GET", "/v3/appendix/user_data"))
        if len(result) != 1:
            raise ClientError(f"Expected one user_data result, got {len(result)}")
        return result[0]

    @cached
    def search_volume(
        self,
        keywords: List[str],
        location_code: int = DEFAULT_LOCATION_CODE,
        language_code: str = DEFAULT_LANGUAGE_CODE,
    ) -> List[dict]:
        """Google Ads monthly search volume, competition, CPC and trend per keyword."""
        _require_keywords(keywords)
        body = [{"keywords": keywords, "location_code": location_code, "language_code": language_code}]
        return self._task_result(
            self._make_request("POST", "/v3/keywords_data/google_ads/search_volume/live", data=body)
        )

    @cached
    def keyword_difficulty(
        self,
        keywords: List[str],
        location_code: int = DEFAULT_LOCATION_CODE,
        language_code: str = DEFAULT_LANGUAGE_CODE,
    ) -> List[dict]:
        """DataForSEO Labs keyword difficulty (0-100) per keyword."""
        _require_keywords(keywords)
        body = [{"keywords": keywords, "location_code": location_code, "language_code": language_code}]
        result = self._task_result(
            self._make_request("POST", "/v3/dataforseo_labs/google/bulk_keyword_difficulty/live", data=body)
        )
        return (result[0].get("items") or []) if result else []

    @cached
    def keyword_ideas(
        self,
        seeds: List[str],
        limit: int = 100,
        filters: Optional[List[str]] = None,
        order_by: Optional[str] = None,
        location_code: int = DEFAULT_LOCATION_CODE,
        language_code: str = DEFAULT_LANGUAGE_CODE,
    ) -> List[dict]:
        """DataForSEO Labs keyword ideas (volume, difficulty, CPC, intent) for seed keywords."""
        _require_keywords(seeds)
        if not 1 <= limit <= MAX_IDEAS_LIMIT:
            raise ClientError(f"--limit must be between 1 and {MAX_IDEAS_LIMIT}, got {limit}")
        task = {"keywords": seeds, "limit": limit, "location_code": location_code, "language_code": language_code}
        api_filters = to_api_filters(filters)
        if api_filters:
            task["filters"] = api_filters
        if order_by:
            task["order_by"] = [order_by]
        result = self._task_result(
            self._make_request("POST", "/v3/dataforseo_labs/google/keyword_ideas/live", data=[task])
        )
        return (result[0].get("items") or []) if result else []


_client: Optional[DataforseoClient] = None


def get_client() -> DataforseoClient:
    """Get or create the global Dataforseo client instance."""
    global _client
    if _client is None:
        _client = DataforseoClient()
    return _client
