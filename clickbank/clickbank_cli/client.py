"""ClickBank REST API client."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence
import random
import time
import warnings

warnings.filterwarnings("ignore", module="urllib3")
import requests
from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import apply_filters, parse_filter_string, validate_filters

from .config import Config, get_config
from .models import (
    Order,
    OrderCount,
    Product,
    ProductCreateResult,
    ProductDeleteResult,
    QuickstatsAccount,
)

activity = get_activity_logger("clickbank")

DEFAULT_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
CLICKBANK_PAGE_SIZE = 100
JSON_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}

ORDER_LIST_API_FIELDS = {
    "affiliate",
    "amount",
    "email",
    "item",
    "lastName",
    "postalCode",
    "role",
    "startDate",
    "endDate",
    "tid",
    "type",
    "vendor",
}
ORDER_COUNT_API_FIELDS = {
    "affiliate",
    "email",
    "item",
    "lastName",
    "role",
    "startDate",
    "endDate",
    "tid",
    "type",
    "vendor",
}
ORDER_CLIENT_FILTER_FIELDS = {
    "receipt",
    "transactionTime",
    "transactionType",
    "vendor",
    "affiliate",
    "country",
    "state",
    "lastName",
    "firstName",
    "currency",
    "email",
    "postalCode",
    "role",
    "fullName",
}

PRODUCT_LIST_API_FIELDS = {"type"}
PRODUCT_CLIENT_FILTER_FIELDS = {
    "sku",
    "status",
    "digital",
    "physical",
    "digitalRecurring",
    "physicalRecurring",
    "site",
    "created",
    "updated",
    "language",
    "title",
    "description",
    "deliveryMethod",
    "deliverySpeed",
    "approval_status.status",
}

QUICKSTATS_API_FIELDS = {"account", "startDate", "endDate"}
QUICKSTATS_CLIENT_FILTER_FIELDS = {"nickName"}

PRODUCT_REQUIRED_PARAMS = {"currency", "language", "price", "site", "title"}
PRODUCT_COMPONENT_FIELDS = {"digital", "digitalRecurring", "physical", "physicalRecurring"}
PRODUCT_DIGITAL_FIELDS = {"digital", "digitalRecurring"}
PRODUCT_PHYSICAL_FIELDS = {"physical", "physicalRecurring"}
PRODUCT_RECURRING_FIELDS = {"digitalRecurring", "physicalRecurring"}
PRODUCT_CATEGORY_VALUES = {"EBOOK", "SOFTWARE", "GAMES", "AUDIO", "VIDEO", "MEMBER_SITE"}
PRODUCT_LANGUAGE_VALUES = {"DE", "EN", "ES", "FR", "IT", "PT"}
PRODUCT_FREQUENCY_VALUES = {"WEEKLY", "BI_WEEKLY", "MONTHLY", "QUARTERLY", "YEARLY"}


@dataclass(frozen=True)
class ResponseEnvelope:
    status_code: int
    payload: Any


class ClickBankClient:
    """Client for interacting with ClickBank's REST APIs."""

    def __init__(
        self,
        config: Optional[Config] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.config = config or get_config()
        if not self.config.has_credentials():
            missing = ", ".join(self.config.get_missing_credentials())
            raise ClientError(f"Missing credentials: {missing}. Run 'clickbank auth login'.")

        self.base_url = self.config.base_url
        self.default_headers = {
            **JSON_HEADERS,
            "Authorization": self.config.api_key,
        }
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.timeout = timeout

    def _build_headers(self, page: Optional[int] = None) -> dict[str, str]:
        headers = dict(self.default_headers)
        if page is not None and page > 1:
            headers["Page"] = str(page)
        return headers

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_delay)

        delay = self.base_delay * (2 ** attempt)
        jitter_window = delay * self.jitter
        delay += random.uniform(-jitter_window, jitter_window)
        return min(delay, self.max_delay)

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
            return response.text or "Unknown error"

        if isinstance(payload, dict):
            if "message" in payload and payload["message"]:
                return str(payload["message"])
            if "error" in payload and payload["error"]:
                return str(payload["error"])
        return str(payload)

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Optional[Sequence[tuple[str, str]] | dict[str, str]] = None,
        page: Optional[int] = None,
    ) -> ResponseEnvelope:
        url = f"{self.base_url}{endpoint}"
        last_exception: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self._build_headers(page=page),
                    params=params,
                    json=None,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_exception = exc
                if attempt == self.max_retries:
                    break
                delay = self._calculate_retry_delay(attempt)
                activity.warning("Retrying ClickBank request after transport error: %s", exc)
                time.sleep(delay)
                continue

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                delay = self._calculate_retry_delay(attempt, self._get_retry_after(response))
                activity.warning(
                    "Retrying ClickBank request after HTTP %s for %s %s",
                    response.status_code,
                    method,
                    endpoint,
                )
                time.sleep(delay)
                continue

            if not response.ok:
                detail = self._extract_error_detail(response)
                raise ClientError(f"HTTP {response.status_code}: {detail}")

            if response.status_code == 204 or not response.content:
                return ResponseEnvelope(status_code=response.status_code, payload=None)

            try:
                payload = response.json()
            except ValueError as exc:
                raise ClientError(f"ClickBank returned non-JSON content for {endpoint}: {exc}") from exc

            return ResponseEnvelope(status_code=response.status_code, payload=payload)

        raise ClientError(f"Request failed after {self.max_retries + 1} attempts: {last_exception}")

    def _extract_list(self, payload: Any, *, context: str) -> list[Any]:
        if payload is None:
            return []
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            if len(payload) == 1:
                only_value = next(iter(payload.values()))
                if isinstance(only_value, list):
                    return only_value
                if isinstance(only_value, dict):
                    return [only_value]
        raise ClientError(f"Unexpected ClickBank payload for {context}: {payload!r}")

    def _extract_object(self, payload: Any, *, context: str) -> dict[str, Any]:
        if isinstance(payload, dict):
            if len(payload) == 1:
                only_value = next(iter(payload.values()))
                if isinstance(only_value, dict):
                    return only_value
            return payload
        if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
            return payload[0]
        raise ClientError(f"Unexpected ClickBank payload for {context}: {payload!r}")

    def _extract_string(self, payload: Any, *, context: str) -> str:
        if isinstance(payload, str):
            return payload
        if isinstance(payload, dict) and len(payload) == 1:
            only_value = next(iter(payload.values()))
            if isinstance(only_value, str):
                return only_value
        raise ClientError(f"Unexpected ClickBank payload for {context}: {payload!r}")

    def _extract_count(self, payload: Any, *, context: str) -> int:
        if isinstance(payload, int):
            return payload
        if isinstance(payload, str) and payload.isdigit():
            return int(payload)
        if isinstance(payload, dict):
            if "count" in payload:
                return int(payload["count"])
            if len(payload) == 1:
                only_value = next(iter(payload.values()))
                if isinstance(only_value, (int, str)):
                    return int(only_value)
        raise ClientError(f"Unexpected ClickBank payload for {context}: {payload!r}")

    def _translate_filter_group(
        self,
        filter_string: str,
        *,
        api_fields: set[str],
        client_fields: set[str],
    ) -> tuple[dict[str, str], Optional[str]]:
        api_params: dict[str, str] = {}
        client_conditions: list[str] = []

        for field, op, value in parse_filter_string(filter_string):
            condition = f"{field}:{op}" if value is None else f"{field}:{op}:{value}"
            if field in api_fields and op == "eq":
                if value is None:
                    raise ClientError(f"Filter '{condition}' requires a value.")
                api_params[field] = value
                continue
            if field in client_fields:
                client_conditions.append(condition)
                continue
            raise ClientError(f"Unsupported filter for ClickBank endpoint: {condition}")

        if not client_conditions:
            return api_params, None
        return api_params, ",".join(client_conditions)

    def _prepare_filters(
        self,
        filters: Optional[list[str]],
        *,
        api_fields: set[str],
        client_fields: set[str],
    ) -> tuple[dict[str, str], list[str]]:
        if not filters:
            return {}, []

        validate_filters(filters)
        api_params: dict[str, str] = {}
        client_filters: list[str] = []

        for filter_string in filters:
            group_params, group_client = self._translate_filter_group(
                filter_string,
                api_fields=api_fields,
                client_fields=client_fields,
            )
            for key, value in group_params.items():
                if key in api_params and api_params[key] != value:
                    raise ClientError(f"Conflicting ClickBank filter values for '{key}'.")
                api_params[key] = value
            if group_client:
                client_filters.append(group_client)

        return api_params, client_filters

    def _require_order_date_pair(self, params: dict[str, str]):
        start_date = params.get("startDate")
        end_date = params.get("endDate")
        if (start_date and not end_date) or (end_date and not start_date):
            raise ClientError("ClickBank orders filters require both startDate and endDate together.")

    def _collect_paginated_items(
        self,
        endpoint: str,
        *,
        params: Optional[dict[str, str]] = None,
        page: int = 1,
        limit: int = CLICKBANK_PAGE_SIZE,
        client_filters: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        current_page = page

        while len(rows) < limit:
            envelope = self._request("GET", endpoint, params=params, page=current_page)
            page_rows = self._extract_list(envelope.payload, context=endpoint)
            if client_filters:
                page_rows = apply_filters(page_rows, client_filters)
            rows.extend(page_rows[: limit - len(rows)])
            if envelope.status_code != 206:
                break
            current_page += 1

        return rows

    def _validate_product_params(self, params: Sequence[tuple[str, str]]):
        values: dict[str, list[str]] = {}
        for key, value in params:
            values.setdefault(key, []).append(value)

        missing = sorted(PRODUCT_REQUIRED_PARAMS.difference(values))
        if missing:
            raise ClientError(
                f"Missing required ClickBank product parameters: {', '.join(missing)}."
            )

        components = {field for field in PRODUCT_COMPONENT_FIELDS if "true" in values.get(field, [])}
        if not components:
            raise ClientError(
                "At least one component must be enabled with digital=true, digitalRecurring=true, "
                "physical=true, or physicalRecurring=true."
            )

        if "language" in values:
            language = values["language"][-1]
            if language not in PRODUCT_LANGUAGE_VALUES:
                raise ClientError(
                    f"Invalid ClickBank language '{language}'. Expected one of: "
                    f"{', '.join(sorted(PRODUCT_LANGUAGE_VALUES))}."
                )

        for category in values.get("categories", []):
            if category not in PRODUCT_CATEGORY_VALUES:
                raise ClientError(
                    f"Invalid ClickBank category '{category}'. Expected one of: "
                    f"{', '.join(sorted(PRODUCT_CATEGORY_VALUES))}."
                )

        if components.intersection(PRODUCT_DIGITAL_FIELDS) and "categories" not in values:
            raise ClientError("Digital ClickBank products require at least one categories=<value> parameter.")

        if components.intersection(PRODUCT_PHYSICAL_FIELDS):
            required_physical = {"deliveryMethod", "deliverySpeed", "shippingProfile", "description"}
            missing_physical = sorted(required_physical.difference(values))
            if missing_physical:
                raise ClientError(
                    "Physical ClickBank products require: "
                    + ", ".join(missing_physical)
                    + "."
                )

        if components.intersection(PRODUCT_RECURRING_FIELDS):
            required_recurring = {
                "description",
                "duration",
                "frequency",
                "rebillCommission",
                "rebillPrice",
                "trialPeriod",
            }
            missing_recurring = sorted(required_recurring.difference(values))
            if missing_recurring:
                raise ClientError(
                    "Recurring ClickBank products require: "
                    + ", ".join(missing_recurring)
                    + "."
                )
            frequency = values["frequency"][-1]
            if frequency not in PRODUCT_FREQUENCY_VALUES:
                raise ClientError(
                    f"Invalid ClickBank frequency '{frequency}'. Expected one of: "
                    f"{', '.join(sorted(PRODUCT_FREQUENCY_VALUES))}."
                )

        if "pitchPage" not in values and "mobilePitchPage" not in values:
            raise ClientError("ClickBank products require pitchPage=<url> or mobilePitchPage=<url>.")

        if "thankYouPage" not in values and "mobileThankYouPage" not in values:
            raise ClientError("ClickBank products require thankYouPage=<url> or mobileThankYouPage=<url>.")

    def get_order(self, receipt: str, *, sku: Optional[str] = None) -> list[Order]:
        params = {"sku": sku} if sku else None
        payload = self._request("GET", f"/orders2/{receipt}", params=params).payload
        return [Order(**row) for row in self._extract_list(payload, context=f"/orders2/{receipt}")]

    def get_order_upsells(self, receipt: str) -> list[Order]:
        payload = self._request("GET", f"/orders2/{receipt}/upsells").payload
        return [
            Order(**row)
            for row in self._extract_list(payload, context=f"/orders2/{receipt}/upsells")
        ]

    def list_orders(
        self,
        *,
        limit: int = CLICKBANK_PAGE_SIZE,
        page: int = 1,
        filters: Optional[list[str]] = None,
    ) -> list[Order]:
        api_params, client_filters = self._prepare_filters(
            filters,
            api_fields=ORDER_LIST_API_FIELDS,
            client_fields=ORDER_CLIENT_FILTER_FIELDS,
        )
        self._require_order_date_pair(api_params)
        rows = self._collect_paginated_items(
            "/orders2/list",
            params=api_params or None,
            page=page,
            limit=limit,
            client_filters=client_filters or None,
        )
        return [Order(**row) for row in rows]

    def count_orders(self, *, filters: Optional[list[str]] = None) -> OrderCount:
        api_params, client_filters = self._prepare_filters(
            filters,
            api_fields=ORDER_COUNT_API_FIELDS,
            client_fields=set(),
        )
        if client_filters:
            raise ClientError("orders count supports only documented API-translatable filters.")
        self._require_order_date_pair(api_params)
        payload = self._request("GET", "/orders2/count", params=api_params or None).payload
        return OrderCount(count=self._extract_count(payload, context="/orders2/count"))

    def get_product(self, sku: str, *, site: str) -> Product:
        payload = self._request("GET", f"/products/{sku}", params={"site": site}).payload
        product = self._extract_object(payload, context=f"/products/{sku}")
        return Product(**product)

    def list_products(
        self,
        *,
        site: str,
        limit: int = CLICKBANK_PAGE_SIZE,
        page: int = 1,
        filters: Optional[list[str]] = None,
    ) -> list[Product]:
        api_params, client_filters = self._prepare_filters(
            filters,
            api_fields=PRODUCT_LIST_API_FIELDS,
            client_fields=PRODUCT_CLIENT_FILTER_FIELDS,
        )
        params = {"site": site, **api_params}
        rows = self._collect_paginated_items(
            "/products/list",
            params=params,
            page=page,
            limit=limit,
            client_filters=client_filters or None,
        )
        return [Product(**row) for row in rows]

    def create_product(self, sku: str, params: Sequence[tuple[str, str]]) -> ProductCreateResult:
        self._validate_product_params(params)
        payload = self._request("PUT", f"/products/{sku}", params=params).payload
        return ProductCreateResult(sku=self._extract_string(payload, context=f"/products/{sku}"))

    def delete_product(self, sku: str, *, site: str) -> ProductDeleteResult:
        self._request("DELETE", f"/products/{sku}", params={"site": site})
        return ProductDeleteResult(sku=sku, site=site, deleted=True)

    def list_quickstats_accounts(self) -> list[QuickstatsAccount]:
        payload = self._request("GET", "/quickstats/accounts").payload
        rows = self._extract_list(payload, context="/quickstats/accounts")
        accounts = []
        for row in rows:
            if isinstance(row, str):
                accounts.append(QuickstatsAccount(nickName=row))
                continue
            accounts.append(QuickstatsAccount(**row))
        return accounts

    def count_quickstats(self, *, filters: Optional[list[str]] = None) -> list[QuickstatsAccount]:
        api_params, client_filters = self._prepare_filters(
            filters,
            api_fields=QUICKSTATS_API_FIELDS,
            client_fields=set(),
        )
        if client_filters:
            raise ClientError("quickstats count supports only account, startDate, and endDate filters.")
        payload = self._request("GET", "/quickstats/count", params=api_params or None).payload
        rows = self._extract_list(payload, context="/quickstats/count")
        return [QuickstatsAccount(**row) for row in rows]

    def get_quickstats_account(self, account: str) -> list[QuickstatsAccount]:
        return self.list_quickstats(filters=[f"account:eq:{account}"])

    def list_quickstats(
        self,
        *,
        limit: int = CLICKBANK_PAGE_SIZE,
        page: int = 1,
        filters: Optional[list[str]] = None,
    ) -> list[QuickstatsAccount]:
        api_params, client_filters = self._prepare_filters(
            filters,
            api_fields=QUICKSTATS_API_FIELDS,
            client_fields=QUICKSTATS_CLIENT_FILTER_FIELDS,
        )
        rows = self._collect_paginated_items(
            "/quickstats/list",
            params=api_params or None,
            page=page,
            limit=limit,
            client_filters=client_filters or None,
        )
        return [QuickstatsAccount(**row) for row in rows]


_client: Optional[ClickBankClient] = None


def get_client() -> ClickBankClient:
    """Get or create the global ClickBank client instance."""
    global _client
    if _client is None:
        _client = ClickBankClient()
    return _client


from .browser import ClickBankBrowser  # noqa: E402  (re-export for fleet compliance)


def get_browser() -> ClickBankBrowser:
    """Get the ClickBank BrowserAutomation subclass instance (delegates to config)."""
    return get_config().get_browser()
