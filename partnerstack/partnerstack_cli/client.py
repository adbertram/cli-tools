"""PartnerStack Partner API client."""
from typing import Any, Dict, List, Optional
import random
import time

import requests

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import FilterValidationError, parse_filter_string, validate_filters

from .config import get_config
from .models import (
    Application,
    FormTemplate,
    MarketplaceProgram,
    Partnership,
    Reward,
    create_application,
    create_form_template,
    create_marketplace_program,
    create_partnership,
    create_reward,
)


DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
AUTH_BEARER = "bearer"
AUTH_BASIC = "basic"

REWARD_EQUALITY_FILTERS = {
    "company_key",
    "payment_status",
    "order_by",
    "group_key",
    "customer_key",
    "invoice_key",
    "status",
    "exclude_drip_rewards",
    "hide_archived_rewards",
    "empty_line_id",
    "keywords",
    "description",
    "distinct_description",
    "distinct_decline_reason",
    "decline_reason",
    "invoiceable",
    "currency",
}


class PartnerstackClient:
    """Client for the PartnerStack Partner API."""

    def __init__(
        self,
        auth_type: str = AUTH_BEARER,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = get_config()
        self.base_url = self.config.base_url.rstrip("/")
        self.auth_type = auth_type
        self.auth = None
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if auth_type == AUTH_BEARER:
            self._require_credentials(("API_KEY",), "partnerstack auth login")
            self.headers["Authorization"] = f"Bearer {self.config.api_key}"
        elif auth_type == AUTH_BASIC:
            self._require_credentials(("USERNAME", "PASSWORD"), "partnerstack auth login-basic")
            self.auth = (self.config.username, self.config.password)
        else:
            raise ClientError(f"Unknown PartnerStack auth type: {auth_type}")
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

    def _require_credentials(self, fields: tuple[str, ...], command: str) -> None:
        """Require the exact credential fields needed by this client instance."""
        missing = [field for field in fields if not self.config._get(field)]
        if missing:
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                f"Run '{command}' to authenticate."
            )

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """Calculate retry delay with exponential backoff and jitter."""
        if retry_after is not None:
            return min(retry_after, self.max_delay)

        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        return min(delay + random.uniform(-jitter_range, jitter_range), self.max_delay)

    def _get_retry_after(self, response: requests.Response) -> Optional[float]:
        """Return Retry-After seconds when present."""
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return None
        return float(retry_after)

    def _extract_error_detail(self, response: requests.Response) -> str:
        """Extract PartnerStack's documented error message."""
        error_body = response.json()
        if "message" not in error_body:
            raise ClientError("PartnerStack error response did not include message")
        return str(error_body["message"])

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make an HTTP request to PartnerStack."""
        url = f"{self.base_url}{endpoint}"
        last_exception: Optional[requests.exceptions.RequestException] = None
        last_response: Optional[requests.Response] = None

        for attempt in range(self.max_retries + 1):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    auth=self.auth,
                    params=params,
                    json=data,
                    timeout=30,
                )
                last_response = response

                if response.status_code in RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                    retry_after = self._get_retry_after(response)
                    time.sleep(self._calculate_retry_delay(attempt, retry_after))
                    continue
                break
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ) as e:
                last_exception = e
                if attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt))
                    continue
                break

        if last_response is None:
            raise ClientError(f"Request failed after {self.max_retries + 1} attempts: {last_exception}")

        if not last_response.ok:
            raise ClientError(f"HTTP {last_response.status_code}: {self._extract_error_detail(last_response)}")

        return last_response.json()

    def _translate_reward_filters(self, filters: Optional[List[str]]) -> Dict[str, Any]:
        """Translate supported reward filters into PartnerStack query parameters."""
        if not filters:
            return {}

        validate_filters(filters)
        params: Dict[str, Any] = {}
        for filter_string in filters:
            for field, op, value in parse_filter_string(filter_string):
                if field == "created_at" and op == "gte":
                    self._set_unique_param(params, "min_created", value)
                    continue
                if field == "created_at" and op == "lte":
                    self._set_unique_param(params, "max_created", value)
                    continue
                if field in REWARD_EQUALITY_FILTERS and op == "eq":
                    self._set_unique_param(params, field, value)
                    continue
                raise FilterValidationError(
                    f"Unsupported PartnerStack reward filter '{field}:{op}'. "
                    "Supported equality filters: "
                    f"{', '.join(sorted(REWARD_EQUALITY_FILTERS))}; "
                    "created_at supports gte and lte."
                )
        return params

    def _set_unique_param(self, params: Dict[str, Any], name: str, value: Any) -> None:
        """Set a query parameter once."""
        if name in params:
            raise ClientError(f"Duplicate PartnerStack query parameter: {name}")
        params[name] = value

    def list_rewards(
        self,
        limit: int = 100,
        filters: Optional[List[str]] = None,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
    ) -> List[Reward]:
        """List rewards with API-level pagination and filtering."""
        params: Dict[str, Any] = {"limit": limit}
        params.update(self._translate_reward_filters(filters))

        if starting_after is not None and ending_before is not None:
            raise ClientError("starting_after and ending_before are mutually exclusive")
        if starting_after is not None:
            params["starting_after"] = starting_after
        if ending_before is not None:
            params["ending_before"] = ending_before

        response = self._make_request("GET", "/rewards", params=params)
        data = response["data"]
        items = data["items"]
        return [create_reward(item) for item in items]

    def get_reward(self, reward_key: str) -> Reward:
        """Get one reward by key using PartnerStack's documented keyword filter."""
        rewards = self.list_rewards(limit=250, filters=[f"keywords:eq:{reward_key}"])
        matches = [reward for reward in rewards if reward.key == reward_key]
        if len(matches) != 1:
            raise ClientError(f"Expected one reward with key {reward_key}, found {len(matches)}")
        return matches[0]

    # ------------------------------------------------------------------
    # Marketplace (discovery) operations
    # ------------------------------------------------------------------

    def list_marketplace_programs(
        self,
        limit: int = 10,
        filters: Optional[List[str]] = None,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
    ) -> List[MarketplaceProgram]:
        """List active marketplace-listed programs.

        Wraps GET /api/v2/marketplace/programs. Returns up to ``limit`` items
        (1-250). Cursor params ``starting_after`` and ``ending_before`` are
        mutually exclusive per PartnerStack's documented constraint.
        """
        params: Dict[str, Any] = {"limit": limit}
        params.update(self._translate_marketplace_filters(filters))
        if starting_after is not None and ending_before is not None:
            raise ClientError("starting_after and ending_before are mutually exclusive")
        if starting_after is not None:
            params["starting_after"] = starting_after
        if ending_before is not None:
            params["ending_before"] = ending_before

        response = self._make_request("GET", "/marketplace/programs", params=params)
        data = response["data"]
        items = data["items"]
        return [create_marketplace_program(item) for item in items]

    _MARKETPLACE_EQUALITY_FILTERS = {"category"}

    def _translate_marketplace_filters(self, filters: Optional[List[str]]) -> Dict[str, Any]:
        """Translate `--filter field:op:value` strings into marketplace query params."""
        if not filters:
            return {}

        validate_filters(filters)
        params: Dict[str, Any] = {}
        for filter_string in filters:
            for field, op, value in parse_filter_string(filter_string):
                if field == "created_at" and op == "gte":
                    self._set_unique_param(params, "min_created", value)
                    continue
                if field == "created_at" and op == "lte":
                    self._set_unique_param(params, "max_created", value)
                    continue
                if field in self._MARKETPLACE_EQUALITY_FILTERS and op == "eq":
                    self._set_unique_param(params, field, value)
                    continue
                raise FilterValidationError(
                    f"Unsupported marketplace filter '{field}:{op}'. "
                    "Supported: category:eq, created_at:gte, created_at:lte."
                )
        return params

    def get_marketplace_program(self, company_key: str) -> MarketplaceProgram:
        """Retrieve a single marketplace program by company_key.

        PartnerStack documents GET /api/v2/marketplace/programs/{company_key}
        but in practice that endpoint returns 404 for the company_keys returned
        by GET /api/v2/marketplace/programs against an active partner-API key.
        This method therefore pages through the list endpoint (which is the
        documented discovery surface) and returns the program whose ``key``
        matches.
        """
        cursor: Optional[str] = None
        for _ in range(20):  # bounded to avoid runaway pagination
            page = self.list_marketplace_programs(limit=250, starting_after=cursor)
            if not page:
                break
            for program in page:
                if program.key == company_key:
                    return program
            if len(page) < 250:
                break
            cursor = page[-1].key
        raise ClientError(f"No marketplace program found with company_key '{company_key}'")

    # ------------------------------------------------------------------
    # Partnerships (post-approval) operations
    # ------------------------------------------------------------------

    def list_partnerships(
        self,
        limit: int = 10,
        filters: Optional[List[str]] = None,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
    ) -> List[Partnership]:
        """List partnerships (post-approval program relationships).

        Wraps GET /api/v2/partnerships.
        """
        params: Dict[str, Any] = {"limit": limit}
        params.update(self._translate_partnership_filters(filters))
        if starting_after is not None and ending_before is not None:
            raise ClientError("starting_after and ending_before are mutually exclusive")
        if starting_after is not None:
            params["starting_after"] = starting_after
        if ending_before is not None:
            params["ending_before"] = ending_before

        response = self._make_request("GET", "/partnerships", params=params)
        data = response["data"]
        items = data["items"]
        return [create_partnership(item) for item in items]

    _PARTNERSHIP_VALID_ORDER_BY = {"-created_at", "created_at", "-updated_at", "updated_at"}
    _PARTNERSHIP_VALID_HAS_SUB_ID = {"true", "false", "null"}
    _PARTNERSHIP_BOOL_FIELDS = {"include_offers", "include_archived"}

    def _translate_partnership_filters(self, filters: Optional[List[str]]) -> Dict[str, Any]:
        """Translate `--filter field:op:value` strings into partnership query params."""
        if not filters:
            return {}

        validate_filters(filters)
        params: Dict[str, Any] = {}
        for filter_string in filters:
            for field, op, value in parse_filter_string(filter_string):
                if op != "eq":
                    raise FilterValidationError(
                        f"Unsupported partnership filter operator '{op}'. Only 'eq' is supported."
                    )
                if field == "order_by":
                    if value not in self._PARTNERSHIP_VALID_ORDER_BY:
                        raise FilterValidationError(
                            f"Invalid order_by value '{value}'. "
                            f"Supported: {', '.join(sorted(self._PARTNERSHIP_VALID_ORDER_BY))}."
                        )
                    self._set_unique_param(params, "order_by", value)
                    continue
                if field == "has_sub_id":
                    if value not in self._PARTNERSHIP_VALID_HAS_SUB_ID:
                        raise FilterValidationError(
                            f"Invalid has_sub_id value '{value}'. Supported: true, false, null."
                        )
                    self._set_unique_param(params, "has_sub_id", value)
                    continue
                if field in self._PARTNERSHIP_BOOL_FIELDS:
                    if value not in ("true", "false"):
                        raise FilterValidationError(
                            f"Invalid boolean value for '{field}': '{value}'. Use 'true' or 'false'."
                        )
                    self._set_unique_param(params, field, value)
                    continue
                raise FilterValidationError(
                    f"Unsupported partnership filter '{field}'. "
                    "Supported: order_by, has_sub_id, include_offers, include_archived."
                )
        return params

    # ------------------------------------------------------------------
    # Form template operations
    # ------------------------------------------------------------------

    _FORM_TEMPLATE_EQUALITY_FILTERS = {"group", "target_type", "mold_keys"}

    def _translate_form_template_filters(self, filters: Optional[List[str]]) -> Dict[str, Any]:
        """Translate `--filter field:op:value` strings into form-template query params."""
        if not filters:
            return {}

        validate_filters(filters)
        params: Dict[str, Any] = {}
        for filter_string in filters:
            for field, op, value in parse_filter_string(filter_string):
                if field == "created_at" and op == "gte":
                    self._set_unique_param(params, "min_created", value)
                    continue
                if field == "created_at" and op == "lte":
                    self._set_unique_param(params, "max_created", value)
                    continue
                if field == "updated_at" and op == "gte":
                    self._set_unique_param(params, "min_updated", value)
                    continue
                if field == "updated_at" and op == "lte":
                    self._set_unique_param(params, "max_updated", value)
                    continue
                if field in self._FORM_TEMPLATE_EQUALITY_FILTERS and op == "eq":
                    self._set_unique_param(params, field, value)
                    continue
                raise FilterValidationError(
                    f"Unsupported form-template filter '{field}:{op}'. "
                    "Supported equality filters: "
                    f"{', '.join(sorted(self._FORM_TEMPLATE_EQUALITY_FILTERS))}; "
                    "created_at and updated_at support gte and lte."
                )
        return params

    def get_form_template(self, form_template_key: str) -> FormTemplate:
        """Retrieve a single form template by key.

        PartnerStack does not document a ``GET /form-templates/{key}`` endpoint.
        This method pages through ``GET /api/v2/form-templates`` and returns
        the template whose ``key`` matches.
        """
        cursor: Optional[str] = None
        for _ in range(20):  # bounded to avoid runaway pagination
            page = self.list_form_templates(limit=250, starting_after=cursor)
            if not page:
                break
            for template in page:
                if template.key == form_template_key:
                    return template
            if len(page) < 250:
                break
            cursor = page[-1].key
        raise ClientError(
            f"No form template found with key '{form_template_key}'"
        )

    def list_form_templates(
        self,
        limit: int = 10,
        filters: Optional[List[str]] = None,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
    ) -> List[FormTemplate]:
        """List form templates via Basic-auth GET /api/v2/form-templates."""
        params: Dict[str, Any] = {"limit": limit}
        params.update(self._translate_form_template_filters(filters))
        if starting_after is not None and ending_before is not None:
            raise ClientError("starting_after and ending_before are mutually exclusive")
        if starting_after is not None:
            params["starting_after"] = starting_after
        if ending_before is not None:
            params["ending_before"] = ending_before

        response = self._make_request("GET", "/form-templates", params=params)
        data = response["data"]
        items = data["items"]
        return [create_form_template(item) for item in items]

    # ------------------------------------------------------------------
    # Applications operations
    # ------------------------------------------------------------------

    def create_application(self, group_slug: str, meta: Dict[str, Any]) -> Application:
        """Create a partner application via Basic-auth POST /api/v2/applications."""
        body = {"group_slug": group_slug, "meta": meta}
        response = self._make_request("POST", "/applications", data=body)
        data = response["data"]
        return create_application(data)

_clients: Dict[str, PartnerstackClient] = {}


def get_client(auth_type: str = AUTH_BEARER) -> PartnerstackClient:
    """Get or create a global PartnerStack client for one auth type."""
    if auth_type not in _clients:
        _clients[auth_type] = PartnerstackClient(auth_type=auth_type)
    return _clients[auth_type]
