"""DoorDash client.

Authentication is browser-based (cookies captured via `doordash auth login`);
data operations are pure GraphQL POSTs that reuse the saved cookies.
"""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from cli_tools_shared.data_cache import cached
from cli_tools_shared.http_session import BrowserAuthState, BrowserAuthStateError

from .browser import DoorDashBrowser
from .config import get_config
from .models import Order, Restaurant
from .reorder import ReorderResult, run_reorder_flow


class ClientError(Exception):
    pass


class AuthenticationError(ClientError):
    pass


# DoorDash order UUIDs look like 0c3b80bc-fdf9-4ce8-9b32-5e1fbca9c900.
# The reorder browser flow MUST navigate by UUID; numeric merchant IDs cause
# the SPA to hang on the get-order-status endpoint with HTTP 400.
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_STORE_ID_RE = re.compile(r"/(?:convenience/)?store/(\d+)")
_UUID_RESOLVE_LIMIT = 1000
_QUERIES_DIR = Path(__file__).parent / "data" / "queries"

# Lookup of (stage, message_substring) -> user-facing AuthenticationError text.
# `stage` is "load" (state construction) or "cookies" (cookie extraction).
# Within each stage, the first matching substring wins; "" matches anything.
_AUTH_ERROR_MESSAGES = {
    "load": [
        ("does not exist", "No saved browser session. Run 'doordash auth login'."),
        ("", "Saved browser session is invalid ({exc}). Run 'doordash auth login --force' to refresh."),
    ],
    "cookies": [
        ("", "No usable DoorDash cookies in saved session ({exc}). Run 'doordash auth login --force' to refresh."),
    ],
}


def _load_query(name: str) -> str:
    return (_QUERIES_DIR / f"{name}.graphql").read_text(encoding="utf-8")


class DoordashClient:
    BASE_URL = "https://www.doordash.com"
    # API returns empty list if limit > 30
    MAX_PAGE_SIZE = 30

    def __init__(self):
        self.config = get_config()
        self._browser: Optional[DoorDashBrowser] = None
        self._http_client: Optional[httpx.Client] = None

    @property
    def browser(self) -> DoorDashBrowser:
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    @property
    def http_client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = self._create_http_client()
        return self._http_client

    def _create_http_client(self) -> httpx.Client:
        cookies = self._load_session_cookies()
        csrf_token = cookies.get("XSRF-TOKEN") or cookies.get("csrf_token")
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "Origin": self.BASE_URL,
            "Referer": f"{self.BASE_URL}/",
        }
        if csrf_token:
            headers.update(
                {
                    "x-csrf-token": csrf_token,
                    "x-csrftoken": csrf_token,
                    "x-xsrf-token": csrf_token,
                }
            )
        return httpx.Client(
            base_url=self.BASE_URL,
            cookies=cookies,
            headers=headers,
            timeout=30.0,
            follow_redirects=True,
        )

    def _load_session_cookies(self) -> Dict[str, str]:
        stage = "load"
        try:
            state = BrowserAuthState.from_config(self.config)
            stage = "cookies"
            cookies = state.cookies_for_host("www.doordash.com", allowed_domains=("doordash.com",))
        except BrowserAuthStateError as exc:
            message = str(exc)
            for substring, template in _AUTH_ERROR_MESSAGES[stage]:
                if substring in message:
                    raise AuthenticationError(template.format(exc=message)) from exc
            raise
        return {c.name: c.value for c in cookies}

    def close(self):
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._http_client:
            self._http_client.close()
            self._http_client = None

    def _graphql(self, operation: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            response = self.http_client.post(
                f"/graphql/{operation}?operation={operation}",
                json={"operationName": operation, "variables": variables or {}, "query": _load_query(operation)},
            )
        except httpx.RequestError as exc:
            raise ClientError(f"Request failed: {exc}")

        if response.status_code in (401, 403):
            raise AuthenticationError("Session expired. Run 'doordash auth login'.")
        if not response.is_success:
            raise ClientError(f"HTTP {response.status_code}: {response.text[:300]}")

        data = response.json()
        errors = data.get("errors") or []
        for err in errors:
            msg = (err.get("message") or "").lower()
            if "auth" in msg or "login" in msg or "session" in msg:
                raise AuthenticationError("Session expired. Run 'doordash auth login'.")
        if errors:
            raise ClientError(f"GraphQL error: {errors}")
        return data.get("data") or {}

    # ---------- Orders ----------

    @cached
    def list_orders(self, limit: int = 100, filters: Optional[List[str]] = None) -> List[Order]:
        orders: List[Order] = []
        offset = 0
        while len(orders) < limit:
            page_size = min(self.MAX_PAGE_SIZE, limit - len(orders))
            data = self._graphql(
                "getConsumerOrdersWithDetails",
                {"offset": offset, "limit": page_size, "includeCancelled": True},
            )
            rows = data.get("getConsumerOrdersWithDetails") or []
            if not rows:
                break
            orders.extend(Order(**row) for row in rows[: limit - len(orders)])
            offset += len(rows)
            if len(rows) < page_size:
                break
        return orders

    def get_order(self, order_id: str) -> Order:
        for order in self.list_orders(limit=_UUID_RESOLVE_LIMIT):
            if order.id == order_id or order.orderUuid == order_id:
                return order
        raise ClientError(f"Order not found: {order_id}")

    # ---------- Reorder ----------

    def reorder_order_via_api(self, order_uuid: str) -> str:
        """Build a reorder cart on the server. Returns the new cart UUID.

        This MUTATES server state: it creates a cart in the user's account
        containing all items from the original order. The cart is NOT a placed
        order — it must be submitted via the checkout UI (or --confirm) to
        actually charge the user.
        """
        data = self._graphql("reorderOrder", {"orderUuid": order_uuid})
        payload = data.get("reorderOrder")
        if not payload:
            raise ClientError(f"reorderOrder returned no payload: {data!r}")
        if payload.get("failReason"):
            raise ClientError(f"reorderOrder failed for {order_uuid}: {payload['failReason']}")
        cart_uuid = payload.get("cartUuid")
        if not cart_uuid:
            raise ClientError(f"reorderOrder returned no cartUuid: {payload!r}")
        return cart_uuid

    def resolve_order_uuid(self, order_id_or_uuid: str) -> str:
        """UUIDs are returned as-is; merchant ids are looked up via order history.
        Fail loudly if a merchant id can't be resolved — the reorder flow
        requires a UUID (numeric ids cause the SPA to hang)."""
        if _UUID_RE.match(order_id_or_uuid):
            return order_id_or_uuid
        for order in self.list_orders(limit=_UUID_RESOLVE_LIMIT):
            if order.id == order_id_or_uuid and order.orderUuid:
                return order.orderUuid
        raise ClientError(
            f"Cannot resolve order UUID for {order_id_or_uuid!r}: not found in the "
            f"{_UUID_RESOLVE_LIMIT} most recent orders. Pass the UUID directly."
        )

    def reorder(
        self,
        order_id: str,
        confirm: bool = False,
        log=None,
        debug_dir: Optional[Path] = None,
    ) -> ReorderResult:
        """Re-place a prior order.

        Phase 1 (always): reorderOrder mutation clones the items into a fresh cart.
        Phase 2 (only when confirm=True): browser drives /checkout?orderCartId=...
        through the Place Order button.
        """
        order_uuid = self.resolve_order_uuid(order_id)
        original_order = next(
            (o for o in self.list_orders(limit=_UUID_RESOLVE_LIMIT) if o.orderUuid == order_uuid),
            None,
        )
        if original_order is None:
            raise ClientError(
                f"Order with UUID {order_uuid} not found in the "
                f"{_UUID_RESOLVE_LIMIT} most recent orders."
            )

        cart_uuid = self.reorder_order_via_api(order_uuid)
        result = ReorderResult(
            order_id=order_id,
            order_uuid=order_uuid,
            confirm=confirm,
            submitted=False,
            cart_uuid=cart_uuid,
            cart_url=f"{self.BASE_URL}/checkout?orderCartId={cart_uuid}",
            cart_summary=original_order.cart_summary(),
        )
        if not confirm:
            return result

        flow_result = run_reorder_flow(
            self.browser.get_page(),
            order_id=order_id,
            order_uuid=order_uuid,
            confirm=confirm,
            log=log,
            debug_dir=debug_dir,
            extra_context={"cart_uuid": cart_uuid},
        )
        result.steps = flow_result.steps
        result.submitted = flow_result.submitted
        result.final_url = flow_result.final_url
        return result

    # ---------- Stores ----------

    @cached
    def list_stores(self, limit: int = 50) -> List[Restaurant]:
        page = self.browser.get_page(f"{self.BASE_URL}/home")
        page.wait_for_selector('a[href*="/store/"], a[href*="/convenience/store/"]', timeout=15000)
        page.wait_for_timeout(3000)
        raw_rows = page.evaluate(
            """() => {
                const seen = new Set();
                const anchors = Array.from(
                  document.querySelectorAll('a[href*="/store/"], a[href*="/convenience/store/"]')
                );
                const rows = [];
                for (const anchor of anchors) {
                  const href = anchor.href || "";
                  if (!href || seen.has(href)) continue;
                  const text = (anchor.innerText || "").trim();
                  if (!text || !text.includes("\\n")) continue;
                  seen.add(href);
                  rows.push({
                    href,
                    text,
                    image: anchor.querySelector("img")?.src || null,
                  });
                }
                return rows;
            }"""
        ) or []

        restaurants: List[Restaurant] = []
        seen_ids: set[str] = set()
        for row in raw_rows:
            if len(restaurants) >= limit:
                break
            href = row.get("href") or ""
            match = _STORE_ID_RE.search(href)
            if not match:
                continue
            store_id = match.group(1)
            if store_id in seen_ids:
                continue
            text_lines = [line.strip() for line in (row.get("text") or "").splitlines() if line.strip()]
            if not text_lines:
                continue

            text_blob = " | ".join(text_lines)
            rating_match = re.search(r"\b([0-5](?:\.\d)?)\b", text_blob)
            minutes_match = re.search(r"\b(\d+)\s+min\b", text_blob)
            distance_match = re.search(r"\b(\d+(?:\.\d+)?)\s+mi\b", text_blob)

            restaurants.append(
                Restaurant(
                    id=store_id,
                    name=text_lines[0],
                    description=None,
                    headerImgUrl=row.get("image"),
                    rating=float(rating_match.group(1)) if rating_match else None,
                    deliveryFeeCents=None,
                    deliveryMinutes=int(minutes_match.group(1)) if minutes_match else None,
                    distanceMiles=float(distance_match.group(1)) if distance_match else None,
                    isOpen="closed" not in text_blob.lower(),
                    cuisines=[],
                )
            )
            seen_ids.add(store_id)

        return restaurants

    def _get_user_location(self) -> Dict[str, float]:
        """Fetch the saved delivery address coordinates from the consumer profile.
        Single execution path: if the profile lacks a default address, fail
        loudly. The user must set LATITUDE/LONGITUDE in config, or set a
        default address on doordash.com before browsing stores."""
        data = self._graphql("getConsumerProfile")
        address = (data.get("consumer") or {}).get("defaultAddress") or {}
        lat, lng = address.get("lat"), address.get("lng")
        if lat is None or lng is None:
            raise ClientError(
                "No delivery address available. Set LATITUDE/LONGITUDE in your "
                "doordash config, or set a default address on doordash.com."
            )
        return {"lat": lat, "lng": lng}


_client: Optional[DoordashClient] = None


def get_client() -> DoordashClient:
    global _client
    if _client is None:
        _client = DoordashClient()
    return _client
