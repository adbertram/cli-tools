"""Read-only Airbnb client for public stay search and imported host data reads."""

from __future__ import annotations

import base64
import html
import json
import random
import re
import time
from datetime import date
from typing import Any, Dict, List, Optional

import requests
from cli_tools_shared import get_activity_logger
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.http_session import DEFAULT_BROWSER_JSON_RETRYABLE_STATUS_CODES, required_path

from .config import get_config

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
DEFAULT_CURRENCY = "USD"
DEFAULT_LOCALE = "en"
DEFAULT_RESERVATION_STATUS = "accepted,request"
DEFAULT_STAY_ADULTS = 1
DEFAULT_STAY_CHILDREN = 0
DEFAULT_STAY_INFANTS = 0
DEFAULT_STAY_PETS = 0
DEFAULT_STAY_LIMIT = 20
DEFAULT_LIST_LIMIT = 100
DEFAULT_DETAIL_LOOKUP_LIMIT = 1000
LOGGER = get_activity_logger("airbnb")

INJECTOR_SCRIPT_ID = "data-injector-instances"
DEFERRED_STATE_SCRIPT_ID = "data-deferred-state-0"


def _script_pattern(script_id: str) -> re.Pattern:
    return re.compile(
        rf'<script[^>]*id="{re.escape(script_id)}"[^>]*>(.*?)</script>',
        re.IGNORECASE | re.DOTALL,
    )


INJECTOR_SCRIPT_PATTERN = _script_pattern(INJECTOR_SCRIPT_ID)
DEFERRED_STATE_PATTERN = _script_pattern(DEFERRED_STATE_SCRIPT_ID)
MONEY_PATTERN = re.compile(r"\$?([0-9][0-9,]*(?:\.[0-9]+)?)")
AIRBNB_INBOX_HASH = "0c188dcb32caa896a06638ea4e85e1b9a410fb475c677478bd931769305a9903"
AIRBNB_THREAD_HASH = "dcb05a1212b5bbd6137456ad562915405b97efbb20e466ed0ecba59577f53d49"
MESSAGE_FIELD_FLAGS = {
    "getParticipants": True,
    "getLastReads": True,
    "getThreadState": True,
    "getInboxFields": True,
    "getMessageFields": True,
    "getThreadOnlyFields": True,
    "skipOldMessagePreviewFields": True,
}


def _headers(user_agent: str, referer: str) -> dict:
    return {
        "User-Agent": user_agent,
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "Referer": referer,
    }


def _decode_global_id(global_id: str) -> tuple[str, str]:
    decoded = base64.b64decode(global_id).decode("utf-8")
    if ":" not in decoded:
        raise ClientError(f"Airbnb returned an unsupported global id: {global_id!r}")
    typename, internal_id = decoded.split(":", 1)
    return typename, internal_id


def _encode_global_id(typename: str, internal_id: str) -> str:
    return base64.b64encode(f"{typename}:{internal_id}".encode("utf-8")).decode("ascii")


def _coerce_message_thread_id(thread_id: str) -> str:
    try:
        typename, _internal_id = _decode_global_id(thread_id)
        if typename == "MessageThread":
            return thread_id
    except Exception:
        pass
    return _encode_global_id("MessageThread", thread_id)


def _find_first_key(obj: Any, target_key: str) -> Any:
    if isinstance(obj, dict):
        if target_key in obj:
            return obj[target_key]
        for value in obj.values():
            found = _find_first_key(value, target_key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_first_key(value, target_key)
            if found is not None:
                return found
    return None


def _money_amount(value: Any) -> Optional[float]:
    if not isinstance(value, str):
        return None
    match = MONEY_PATTERN.search(value)
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def _localized_text(value: Any) -> Optional[str]:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        localized = value.get("localizedStringWithTranslationPreference")
        if isinstance(localized, str):
            return localized
    return None


def _string_values(items: Any, key: str) -> list[str]:
    if not isinstance(items, list):
        return []
    return [item[key] for item in items if isinstance(item, dict) and isinstance(item.get(key), str)]


def _decode_demand_listing_id(raw_id: Any) -> str:
    if not isinstance(raw_id, str):
        raise ClientError("Airbnb search result did not include a demand stay listing id.")
    typename, internal_id = _decode_global_id(raw_id)
    if typename != "DemandStayListing":
        raise ClientError(f"Airbnb search result returned unexpected listing id type {typename!r}.")
    return internal_id


def _normalize_stay_search_result(
    raw: dict,
    *,
    base_url: str,
    checkin: str,
    checkout: str,
    adults: int,
) -> dict:
    demand_listing = raw.get("demandStayListing")
    if not isinstance(demand_listing, dict):
        raise ClientError("Airbnb search result did not include demandStayListing data.")

    listing_id = _decode_demand_listing_id(demand_listing.get("id"))
    coordinate = (demand_listing.get("location") or {}).get("coordinate", {})
    structured_price = raw.get("structuredDisplayPrice") or {}
    primary_price = structured_price.get("primaryLine") or {}
    price_details = (structured_price.get("explanationData") or {}).get("priceDetails") or []
    first_price_item = None
    for group in price_details:
        items = group.get("items") if isinstance(group, dict) else None
        if isinstance(items, list) and items:
            first_price_item = items[0]
            break
    first_price_item = first_price_item if isinstance(first_price_item, dict) else {}

    structured_content = raw.get("structuredContent") or {}
    details = _string_values(structured_content.get("primaryLine"), "body")
    name = _localized_text((demand_listing.get("description") or {}).get("name")) or raw.get("subtitle")
    return {
        "id": listing_id,
        "name": name,
        "title": raw.get("title"),
        "subtitle": raw.get("subtitle"),
        "url": (
            f"{base_url}/rooms/{listing_id}"
            f"?check_in={checkin}&check_out={checkout}&adults={adults}"
        ),
        "rating": raw.get("avgRatingLocalized"),
        "rating_label": raw.get("avgRatingA11yLabel"),
        "price_display": primary_price.get("discountedPrice") or primary_price.get("price"),
        "price_total": _money_amount(first_price_item.get("priceString") or primary_price.get("accessibilityLabel")),
        "price_original": _money_amount(primary_price.get("originalPrice")),
        "price_qualifier": primary_price.get("qualifier"),
        "nightly_price_display": first_price_item.get("description"),
        "details": details,
        "badges": _string_values(raw.get("badges"), "text"),
        "payment_messages": _string_values(raw.get("paymentMessages"), "text"),
        "latitude": coordinate.get("latitude") if isinstance(coordinate, dict) else None,
        "longitude": coordinate.get("longitude") if isinstance(coordinate, dict) else None,
        "image_url": (
            raw.get("contextualPictures", [{}])[0].get("picture")
            if isinstance(raw.get("contextualPictures"), list) and raw.get("contextualPictures")
            else None
        ),
    }


class AirbnbClient:
    """Client for read-only Airbnb host data."""

    def __init__(
        self,
        config=None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
        session: Optional[requests.Session] = None,
        require_credentials: bool = True,
    ):
        self.config = config or get_config()
        if require_credentials and not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'airbnb auth login' after signing in to Airbnb in Chrome."
            )
        self.base_url = self.config.base_url.rstrip("/")
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.browser_session = self.config.get_browser() if require_credentials else None
        self.session = session or requests.Session()
        self.session.headers.update(_headers(self.config.browser_user_agent, f"{self.base_url}/hosting"))
        if self.config.airbnb_api_key:
            self.session.headers["X-Airbnb-API-Key"] = self.config.airbnb_api_key
        if require_credentials:
            for cookie in self.config.auth_cookies:
                self.session.cookies.set(
                    cookie["name"],
                    cookie["value"],
                    domain=cookie["domain"],
                    path=cookie.get("path") or "/",
                    secure=bool(cookie.get("secure")),
                )

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_delay)
        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        return min(delay + random.uniform(-jitter_range, jitter_range), self.max_delay)

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
        if isinstance(body, dict) and "errors" in body:
            return str(body["errors"])[:500]
        if isinstance(body, dict) and "message" in body:
            return str(body["message"])
        return str(body)[:500]

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Any] = None,
        referer: Optional[str] = None,
        accept: str = "application/json",
    ) -> requests.Response:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        headers = {"Accept": accept}
        if referer:
            headers["Referer"] = referer
        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None
        max_attempts = self.max_retries + 1
        LOGGER.info("request start method=%s path=%s", method, path)

        for attempt in range(max_attempts):
            try:
                response = self.session.request(method, url, params=params, headers=headers, timeout=30)
                last_response = response
                if (
                    response.status_code in DEFAULT_BROWSER_JSON_RETRYABLE_STATUS_CODES
                    and attempt < self.max_retries
                ):
                    LOGGER.info(
                        "request retry method=%s path=%s status=%s attempt=%s",
                        method,
                        path,
                        response.status_code,
                        attempt + 1,
                    )
                    time.sleep(self._calculate_retry_delay(attempt, self._get_retry_after(response)))
                    continue
                break
            except requests.exceptions.RequestException as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    LOGGER.info("request retry method=%s path=%s error=%s attempt=%s", method, path, exc, attempt + 1)
                    time.sleep(self._calculate_retry_delay(attempt))
                    continue
                break

        if last_exception is not None and last_response is None:
            LOGGER.info("request failed method=%s path=%s attempts=%s", method, path, max_attempts)
            raise ClientError(f"Request failed after {max_attempts} attempts: {last_exception}")
        if last_response is None:
            LOGGER.info("request failed method=%s path=%s no_response=true", method, path)
            raise ClientError("Request failed: no response received")
        if not last_response.ok:
            LOGGER.info("request failed method=%s path=%s status=%s", method, path, last_response.status_code)
            raise ClientError(f"HTTP {last_response.status_code}: {self._extract_error_detail(last_response)}")
        LOGGER.info("request success method=%s path=%s status=%s", method, path, last_response.status_code)
        return last_response

    def _request_json(self, path: str, *, params: Optional[Dict] = None, referer: Optional[str] = None) -> dict:
        response = self._request("GET", path, params=params, referer=referer, accept="application/json")
        try:
            return response.json()
        except ValueError as exc:
            raise ClientError(f"Airbnb returned non-JSON data from {path}.") from exc

    def _request_html(self, path: str, *, params: Optional[Any] = None, referer: Optional[str] = None) -> str:
        return self._request(
            "GET",
            path,
            params=params,
            referer=referer or f"{self.base_url}/hosting",
            accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        ).text

    def _extract_script_state(self, page_path: str, pattern: re.Pattern, label: str, **request_kwargs) -> dict:
        text = self._request_html(page_path, **request_kwargs)
        match = pattern.search(text)
        if not match:
            raise ClientError(f"Airbnb page {page_path} did not include the expected {label}.")
        try:
            state = json.loads(html.unescape(match.group(1)))
        except json.JSONDecodeError as exc:
            raise ClientError(f"Airbnb page {page_path} returned invalid {label} JSON.") from exc
        if not isinstance(state, dict):
            raise ClientError(f"Airbnb page {page_path} returned unsupported {label} JSON.")
        return state

    def _extract_injector_state(self, page_path: str) -> dict:
        return self._extract_script_state(page_path, INJECTOR_SCRIPT_PATTERN, "injector state")

    def _extract_deferred_state(self, page_path: str, params: list[tuple[str, str]]) -> dict:
        return self._extract_script_state(
            page_path,
            DEFERRED_STATE_PATTERN,
            "deferred search state",
            params=params,
            referer=f"{self.base_url}/",
        )

    def _niobe_client_entries(self, page_path: str) -> list:
        state = self._extract_injector_state(page_path)
        for section_entries in state.values():
            if not isinstance(section_entries, list):
                continue
            for entry in section_entries:
                if isinstance(entry, list) and len(entry) >= 2 and entry[0] == "NiobeClientToken":
                    if not isinstance(entry[1], list):
                        raise ClientError(f"Airbnb page {page_path} returned unsupported Niobe client data.")
                    return entry[1]
        raise ClientError(f"Airbnb page {page_path} did not include Niobe client data.")

    def verify_host_session(self) -> None:
        self._niobe_client_entries("/hosting/listings")

    def _viewer_user_global_id(self) -> str:
        for cache_key, payload in self._niobe_client_entries("/hosting/listings"):
            if not isinstance(cache_key, str) or not cache_key.startswith("UnifiedListOfListingsQuery:"):
                continue
            try:
                user_id = payload["data"]["viewer"]["user"]["id"]
            except (KeyError, TypeError):
                continue
            if isinstance(user_id, str) and user_id:
                return user_id
        raise ClientError("Airbnb did not return the current viewer user id.")

    def _viewer_global_id(self) -> str:
        typename, internal_id = _decode_global_id(self._viewer_user_global_id())
        if typename != "User":
            raise ClientError(f"Airbnb returned unexpected viewer id type {typename!r}.")
        return _encode_global_id("Viewer", internal_id)

    @cached
    def list_listings(self, limit: int = DEFAULT_LIST_LIMIT) -> List[dict]:
        LOGGER.info("list_listings limit=%s", limit)
        entries = self._niobe_client_entries("/hosting/listings")
        for cache_key, payload in entries:
            if isinstance(cache_key, str) and cache_key.startswith("BeehiveGetListingsQuery:"):
                listings = _find_first_key(payload, "listings")
                if isinstance(listings, list):
                    return listings[:limit]
        for cache_key, payload in entries:
            if isinstance(cache_key, str) and cache_key.startswith("UnifiedListOfListingsQuery:"):
                listings = _find_first_key(payload, "listingsOfAllTypes")
                edges = listings.get("edges") if isinstance(listings, dict) else None
                if isinstance(edges, list):
                    return [edge.get("node", edge) for edge in edges[:limit]]
        raise ClientError("Airbnb listings page did not include listing data.")

    @cached
    def get_listing(self, listing_id: str) -> dict:
        LOGGER.info("get_listing")
        for listing in self.list_listings(limit=DEFAULT_DETAIL_LOOKUP_LIMIT):
            if str(listing.get("id")) == str(listing_id):
                return listing
        raise ClientError(f"Airbnb listing not found: {listing_id}")

    @cached
    def search_stays(
        self,
        destination: str,
        checkin: str,
        checkout: str,
        adults: int = DEFAULT_STAY_ADULTS,
        children: int = DEFAULT_STAY_CHILDREN,
        infants: int = DEFAULT_STAY_INFANTS,
        pets: int = DEFAULT_STAY_PETS,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        bedrooms: Optional[int] = None,
        beds: Optional[int] = None,
        bathrooms: Optional[int] = None,
        room_types: Optional[list[str]] = None,
        property_type_ids: Optional[list[str]] = None,
        currency: str = DEFAULT_CURRENCY,
        locale: str = DEFAULT_LOCALE,
        limit: int = DEFAULT_STAY_LIMIT,
    ) -> List[dict]:
        LOGGER.info("search_stays destination_set=%s limit=%s", bool(destination), limit)
        params: list[tuple[str, str]] = [
            ("query", destination),
            ("checkin", checkin),
            ("checkout", checkout),
            ("adults", str(adults)),
            ("currency", currency),
            ("locale", locale),
            ("cdnCacheSafe", "false"),
        ]
        for name, value in (("children", children), ("infants", infants), ("pets", pets)):
            if value:
                params.append((name, str(value)))
        for name, value in (
            ("price_min", min_price),
            ("price_max", max_price),
            ("min_bedrooms", bedrooms),
            ("min_beds", beds),
            ("min_bathrooms", bathrooms),
        ):
            if value is not None:
                params.append((name, str(value)))
        for name, values in (("room_types[]", room_types), ("property_type_id[]", property_type_ids)):
            for value in values or []:
                params.append((name, value))

        records: list[dict] = []
        seen: set[str] = set()
        offset = 0
        while len(records) < limit:
            page_params = [*params, ("items_offset", str(offset))]
            state = self._extract_deferred_state("/s/homes", page_params)
            niobe_data = required_path(state, ["niobeClientData"], list)
            payload = required_path(niobe_data, [0, 1], dict)
            results = required_path(
                payload,
                ["data", "presentation", "staysSearch", "results", "searchResults"],
                list,
            )
            if not results:
                break
            records_before = len(records)
            for raw_result in results:
                if not isinstance(raw_result, dict):
                    continue
                record = _normalize_stay_search_result(
                    raw_result,
                    base_url=self.base_url,
                    checkin=checkin,
                    checkout=checkout,
                    adults=adults,
                )
                if record["id"] in seen:
                    continue
                seen.add(record["id"])
                records.append(record)
                if len(records) >= limit:
                    break
            if len(records) == records_before:
                break
            offset += len(results)
        return records[:limit]

    @cached
    def list_reservations(
        self,
        limit: int = DEFAULT_LIST_LIMIT,
        date_min: Optional[str] = None,
        status: str = DEFAULT_RESERVATION_STATUS,
    ) -> List[dict]:
        LOGGER.info("list_reservations limit=%s date_min_set=%s", limit, bool(date_min))
        params = {
            "locale": DEFAULT_LOCALE,
            "currency": DEFAULT_CURRENCY,
            "_format": "for_remy",
            "_limit": limit,
            "_offset": 0,
            "collection_strategy": "for_reservations_list",
            "date_min": date_min or date.today().isoformat(),
            "sort_field": "start_date",
            "sort_order": "asc",
            "status": status,
        }
        data = self._request_json(
            "/api/v2/reservations",
            params=params,
            referer=f"{self.base_url}/hosting/reservations",
        )
        reservations = data.get("reservations")
        if not isinstance(reservations, list):
            raise ClientError("Airbnb reservations API did not return a reservations list.")
        return reservations

    @cached
    def get_reservation(self, reservation_id: str) -> dict:
        LOGGER.info("get_reservation")
        for reservation in self.list_reservations(limit=DEFAULT_DETAIL_LOOKUP_LIMIT):
            for key in ("id", "confirmation_code", "confirmationCode", "code"):
                if str(reservation.get(key)) == str(reservation_id):
                    return reservation
        raise ClientError(f"Airbnb reservation not found: {reservation_id}")

    @cached
    def list_messages(self, limit: int = DEFAULT_LIST_LIMIT) -> List[dict]:
        LOGGER.info("list_messages limit=%s", limit)
        variables = {
            **MESSAGE_FIELD_FLAGS,
            "numRequestedThreads": limit,
            "numPriorityThreads": 20,
            "getPriorityInbox": True,
            "useUserThreadTag": True,
            "userId": self._viewer_global_id(),
            "originType": "USER_INBOX",
            "threadVisibility": "UNARCHIVED",
            "threadTagFilters": [],
            "priorityThreadTagFilters": [{"userThreadTagName": "priority"}],
            "query": None,
            "getInboxOnlyFields": True,
        }
        data = self._persisted_query(
            operation_name="ViaductInboxData",
            operation_hash=AIRBNB_INBOX_HASH,
            variables=variables,
            referer=f"{self.base_url}/hosting/inbox",
        )
        inbox = data.get("data", {}).get("node", {}).get("messagingInbox")
        if not isinstance(inbox, dict):
            raise ClientError("Airbnb inbox API did not return messagingInbox data.")
        records: list[dict] = []
        for key in ("priorityItems", "inboxItems"):
            connection = inbox.get(key)
            if not isinstance(connection, dict):
                continue
            edges = connection.get("edges")
            if isinstance(edges, list):
                records.extend(edge.get("node", edge) for edge in edges)
        return records[:limit]

    @cached
    def get_message_thread(self, thread_id: str) -> dict:
        LOGGER.info("get_message_thread")
        variables = {
            **MESSAGE_FIELD_FLAGS,
            "globalThreadId": _coerce_message_thread_id(thread_id),
            "numRequestedMessages": 40,
            "mockThreadIdentifier": None,
            "mockMessageTestIdentifier": None,
            "forceUgcTranslation": False,
            "isNovaLite": False,
            "getInboxOnlyFields": False,
        }
        return self._persisted_query(
            operation_name="ViaductGetThreadAndDataQuery",
            operation_hash=AIRBNB_THREAD_HASH,
            variables=variables,
            referer=f"{self.base_url}/hosting/inbox",
        )

    def _persisted_query(self, operation_name: str, operation_hash: str, variables: dict, referer: str) -> dict:
        params = {
            "operationName": operation_name,
            "locale": DEFAULT_LOCALE,
            "currency": DEFAULT_CURRENCY,
            "variables": json.dumps(variables, separators=(",", ":")),
            "extensions": json.dumps(
                {"persistedQuery": {"version": 1, "sha256Hash": operation_hash}},
                separators=(",", ":"),
            ),
        }
        return self._request_json(
            f"/api/v3/{operation_name}/{operation_hash}",
            params=params,
            referer=referer,
        )


_client: Optional[AirbnbClient] = None


def get_client() -> AirbnbClient:
    """Get or create the global Airbnb client instance."""
    global _client
    if _client is None:
        _client = AirbnbClient()
    return _client
