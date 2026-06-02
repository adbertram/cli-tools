"""Brick Owl API client.

Uses query parameter authentication (key=API_KEY) matching the Brick Owl API pattern.
POST requests use application/x-www-form-urlencoded.
"""
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import requests

from cli_tools_shared.data_cache import cached

from .config import get_config
from .models import (
    Order,
    OrderDetail,
    OrderItem,
    InventoryLot,
    InventoryStats,
    UserDetails,
    resolve_status,
    is_shipped_status,
    is_not_picked_status,
)

# Retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Concurrent enrichment configuration
DEFAULT_ENRICH_WORKERS = 10

# Fields that require /order/view enrichment (not available in /order/list)
ENRICH_FIELDS = {
    "buyer_name",
    "buyer_username",
    "customer_username",
    "ship_method_name",
    "tracking_id",
    "tracking_number",
    "weight",
    "note",
    "seller_note",
    "iso_order_time",
    "iso_processed_time",
    "customer_email",
    "customer_user_id",
    "ship_first_name",
    "ship_last_name",
    "ship_country_code",
    "ship_country",
    "ship_post_code",
    "ship_street_1",
    "ship_street_2",
    "ship_city",
    "ship_region",
    "ship_phone",
    "payment_method_type",
    "payment_transaction_id",
    "message_count",
}


class ClientError(Exception):
    """Custom exception for Brick Owl API errors."""
    pass


class ApprovalRequiredError(ClientError):
    """Exception for API endpoints that require special approval from Brick Owl."""
    pass


# Endpoints that require approval from Brick Owl
# See: https://www.brickowl.com/api_docs
APPROVAL_REQUIRED_ENDPOINTS = {
    "/catalog/lookup": "catalog lookup",
    "/catalog/availability": "catalog availability",
    "/catalog/inventory": "catalog inventory",
    "/catalog/list": "catalog list",
    "/catalog/bulk": "catalog bulk",
    "/catalog/bulk_lookup": "catalog bulk_lookup",
    "/catalog/cart_basic": "catalog cart",
}


class BrickowlClient:
    """Client for Brick Owl REST API with retry support."""

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = get_config()
        if not self.config.has_api_credentials():
            raise ClientError(
                "Missing API key. Run 'brickowl auth login -c api_key' to configure."
            )
        self.base_url = self.config.base_url
        self.api_key = self.config.api_key
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """Calculate delay using exponential backoff with jitter."""
        if retry_after is not None:
            return min(retry_after, self.max_delay)
        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        delay += random.uniform(-jitter_range, jitter_range)
        return min(delay, self.max_delay)

    def _is_retryable(self, response: Optional[requests.Response], exception: Optional[Exception]) -> bool:
        """Determine if a request should be retried."""
        if exception is not None:
            return isinstance(exception, (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ))
        if response is not None:
            return response.status_code in RETRYABLE_STATUS_CODES
        return False

    def _get(self, endpoint: str, params: Optional[Dict] = None, retry: bool = True) -> Any:
        """Make a GET request to the Brick Owl API.

        Auth is via query parameter 'key'. Returns parsed JSON.
        """
        url = f"{self.base_url}{endpoint}"
        all_params = {"key": self.api_key}
        if params:
            all_params.update({k: v for k, v in params.items() if v is not None})

        return self._execute_request("GET", url, params=all_params, retry=retry)

    def _post(self, endpoint: str, data: Optional[Dict] = None, retry: bool = True) -> Any:
        """Make a POST request to the Brick Owl API.

        Auth key is included in the form body. Uses x-www-form-urlencoded.
        """
        url = f"{self.base_url}{endpoint}"
        all_data = {"key": self.api_key}
        if data:
            all_data.update({k: v for k, v in data.items() if v is not None})

        return self._execute_request("POST", url, data=all_data, retry=retry)

    def _execute_request(
        self,
        method: str,
        url: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        retry: bool = True,
    ) -> Any:
        """Execute an HTTP request with retry logic."""
        headers = {"Accept": "application/json"}
        if method == "POST":
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None
        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params if method == "GET" else None,
                    data=data if method == "POST" else None,
                )
                last_response = response

                if retry and self._is_retryable(response, None) and attempt < self.max_retries:
                    retry_after_header = response.headers.get("Retry-After")
                    retry_after = float(retry_after_header) if retry_after_header else None
                    delay = self._calculate_retry_delay(attempt, retry_after)
                    time.sleep(delay)
                    continue

                break

            except requests.exceptions.RequestException as e:
                last_exception = e
                if retry and self._is_retryable(None, e) and attempt < self.max_retries:
                    delay = self._calculate_retry_delay(attempt)
                    time.sleep(delay)
                    continue
                break

        if last_exception is not None and last_response is None:
            raise ClientError(f"Request failed: {last_exception}")

        if last_response is None:
            raise ClientError("Request failed: no response received")

        if not last_response.ok:
            error_text = last_response.text[:500] if last_response.text else "Unknown error"
            # Check if this is a 403 on an approval-required endpoint
            if last_response.status_code == 403:
                # Extract endpoint from URL
                endpoint = url.replace(self.base_url, "")
                if endpoint in APPROVAL_REQUIRED_ENDPOINTS:
                    command_name = APPROVAL_REQUIRED_ENDPOINTS[endpoint]
                    raise ApprovalRequiredError(
                        f"The '{command_name}' endpoint requires special approval from Brick Owl. "
                        f"Contact Brick Owl at https://www.brickowl.com/contact to request access. "
                        f"Alternative: Use 'brickowl catalog id <ID> <TYPE>' to look up items by external ID (design_id, bricklink, etc.)."
                    )
            raise ClientError(f"Brick Owl API error {last_response.status_code}: {error_text}")

        if last_response.status_code == 204:
            return {}

        return last_response.json()

    # ==================== Order Methods ====================

    @cached
    def list_orders(
        self,
        status: Optional[str] = None,
        list_type: str = "store",
        limit: Optional[int] = None,
        sort_by: Optional[str] = None,
        shipped: Optional[bool] = None,
        not_picked: bool = False,
        enrich: bool = True,
    ) -> List[Order]:
        """List orders with optional filtering.

        Args:
            status: Filter by status (0-8, name, or comma-separated)
            list_type: 'store' for received, 'customer' for placed
            limit: Max results (default 500, max 5000)
            sort_by: 'created' or 'updated'
            shipped: True=shipped only, False=not shipped only
            not_picked: True=only not-picked orders
            enrich: Fetch /order/view for each order to add buyer_name etc.
                    Set False when enrichment fields are not needed.
        """
        # Handle comma-separated statuses
        if status and "," in str(status):
            statuses = [s.strip() for s in str(status).split(",")]
            order_map = {}
            for s in statuses:
                params = {"status": resolve_status(s), "list_type": list_type}
                if limit:
                    params["limit"] = limit
                if sort_by:
                    params["sort_by"] = sort_by
                response = self._get("/order/list", params)
                if isinstance(response, list):
                    for order_data in response:
                        oid = order_data.get("order_id")
                        if oid and oid not in order_map:
                            order_map[oid] = order_data
            all_orders = list(order_map.values())
        else:
            params: Dict[str, Any] = {"list_type": list_type}
            if status is not None:
                params["status"] = resolve_status(str(status))
            if limit:
                params["limit"] = limit
            if sort_by:
                params["sort_by"] = sort_by
            response = self._get("/order/list", params)
            all_orders = response if isinstance(response, list) else []

        # Enrich each order with buyer info from /order/view.
        # The /order/list endpoint does not return buyer_name or customer_username,
        # so we fetch /order/view for each order. Uses concurrent requests
        # for performance. Results are cached individually via get_order's
        # @cached decorator, so repeated calls are fast.
        if enrich:
            all_orders = self._enrich_orders_with_buyer_info(all_orders)

        # Enrich with shipped property
        orders = []
        for data in all_orders:
            status_id = int(data.get("status_id", 0))
            data["shipped"] = is_shipped_status(status_id)
            orders.append(Order(**data))

        # Apply shipped filter
        if shipped is True:
            orders = [o for o in orders if o.shipped]
        elif shipped is False:
            orders = [o for o in orders if not o.shipped]

        # Apply not-picked filter
        if not_picked:
            orders = [o for o in orders if is_not_picked_status(int(o.status_id or 0))]

        return orders

    def _enrich_orders_with_buyer_info(self, orders: List[Dict]) -> List[Dict]:
        """Enrich order list data with buyer info from /order/view.

        The /order/list API does not return buyer_name, customer_username,
        ship_method_name, tracking_number, weight, or seller_note.
        This method fetches /order/view for each order to fill these fields.
        Each /order/view call is cached by get_order's @cached decorator.

        Uses concurrent requests (ThreadPoolExecutor) for performance.
        First run makes one API call per order in parallel.
        Subsequent calls within the cache TTL are served from disk cache.
        """
        # Fields to copy from /order/view into the list data
        VIEW_TO_LIST_FIELDS = {
            "buyer_name": "buyer_name",
            "customer_username": "buyer_username",
            "ship_method_name": "ship_method_name",
            "tracking_number": "tracking_id",
            "weight": "weight",
            "seller_note": "note",
            "iso_order_time": "iso_order_time",
            "iso_processed_time": "iso_processed_time",
        }

        if not orders:
            return orders

        max_workers = int(os.environ.get("ENRICH_WORKERS", DEFAULT_ENRICH_WORKERS))

        def _fetch_detail(order_id: str) -> Optional[Dict]:
            """Fetch /order/view for a single order. Returns detail dict or None."""
            try:
                detail = self.get_order(order_id)
                return detail.model_dump(mode="json")
            except Exception:
                return None

        # Collect order IDs that need enrichment
        order_ids = [o.get("order_id") for o in orders if o.get("order_id")]

        # Fetch all order details concurrently
        detail_map: Dict[str, Dict] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_id = {
                executor.submit(_fetch_detail, oid): oid
                for oid in order_ids
            }
            for future in as_completed(future_to_id):
                oid = future_to_id[future]
                result = future.result()
                if result is not None:
                    detail_map[oid] = result

        # Merge enrichment fields into each order
        enriched = []
        for order_data in orders:
            order_id = order_data.get("order_id")
            if order_id and order_id in detail_map:
                detail_dict = detail_map[order_id]
                for view_field, list_field in VIEW_TO_LIST_FIELDS.items():
                    value = detail_dict.get(view_field)
                    if value is not None:
                        order_data[list_field] = value
            enriched.append(order_data)
        return enriched

    @cached
    def get_order(self, order_id: str) -> OrderDetail:
        """Get full order details."""
        response = self._get("/order/view", {"order_id": order_id})
        return OrderDetail(**response)

    @cached
    def get_order_items(self, order_id: str) -> List[OrderItem]:
        """Get items in an order."""
        response = self._get("/order/items", {"order_id": order_id})
        if isinstance(response, list):
            return [OrderItem(**item) for item in response]
        return []

    def set_order_status(self, order_id: str, status_id: int) -> Dict:
        """Set order status (1-7)."""
        return self._post("/order/set_status", {"order_id": order_id, "status_id": status_id})

    def mark_shipped(self, order_id: str, tracking_id: Optional[str] = None) -> Dict:
        """Mark order as shipped with optional tracking."""
        if tracking_id:
            self._post("/order/tracking", {"order_id": order_id, "tracking_id": tracking_id})
        return self._post("/order/set_status", {"order_id": order_id, "status_id": 5})

    def add_tracking(self, order_id: str, tracking_id: str) -> Dict:
        """Add tracking info to an order."""
        return self._post("/order/tracking", {"order_id": order_id, "tracking_id": tracking_id})

    def update_note(self, order_id: str, note: str) -> Dict:
        """Set seller note on an order."""
        return self._post("/order/note", {"order_id": order_id, "note": note})

    # ==================== Inventory Methods ====================

    @cached
    def list_inventory(
        self,
        item_type: Optional[str] = None,
        active_only: bool = True,
        external_id: Optional[str] = None,
        lot_id: Optional[str] = None,
    ) -> List[InventoryLot]:
        """List inventory lots."""
        params: Dict[str, Any] = {}
        if item_type:
            params["type"] = item_type
        if not active_only:
            params["active_only"] = 0
        if external_id:
            params["external_id_1"] = external_id
        if lot_id:
            params["lot_id"] = lot_id

        response = self._get("/inventory/list", params)
        if isinstance(response, list):
            return [InventoryLot(**lot) for lot in response]
        return []

    @cached
    def get_inventory_lot(self, lot_id: str) -> Optional[InventoryLot]:
        """Get a specific lot by ID."""
        lots = self.list_inventory(lot_id=lot_id)
        return lots[0] if lots else None

    def search_inventory(
        self,
        part_no: str,
        item_type: str = "Part",
        color_id: Optional[int] = None,
    ) -> Dict:
        """Search inventory for a part by number.

        Uses catalog_id_lookup to find BOIDs, then filters inventory lots
        matching the base BOID. Returns bricklink-compatible output format.

        Args:
            part_no: Part number (design ID, BL item no, etc.)
            item_type: Item type (Part, Set, Minifigure, etc.)
            color_id: Optional Brick Owl color ID to filter by

        Returns:
            Dict with "results" list of normalized lot dicts.
        """
        # Step 1: Get BOIDs from catalog
        id_result = self.catalog_id_lookup(part_no, item_type)
        boids = id_result.get("boids", [])
        if not boids:
            return {"results": []}

        # Step 2: Extract ALL unique base BOIDs (strip color suffix, e.g. 612208-38 -> 612208)
        # A single design ID (e.g. 92456 for Friends torsos) can map to hundreds of
        # printed variants, each with a different base BOID. We must check all of them.
        base_boids = {b.split("-")[0] for b in boids}

        # Step 3: Get all inventory lots of this type
        lots = self.list_inventory(item_type=item_type)

        # Step 4: Filter lots where base BOID matches any of the known variants
        matching = [lot for lot in lots if lot.boid and lot.boid.split("-")[0] in base_boids]

        # Step 5: Build color map for name resolution
        colors_raw = self.catalog_colors()
        color_map: Dict[str, str] = {}
        if isinstance(colors_raw, dict):
            for cid, cdata in colors_raw.items():
                if isinstance(cdata, dict):
                    color_map[str(cid)] = cdata.get("name", str(cid))
                else:
                    color_map[str(cid)] = str(cdata)
        elif isinstance(colors_raw, list):
            for c in colors_raw:
                if isinstance(c, dict):
                    color_map[str(c.get("color_id", ""))] = c.get("name", "")

        # Step 6: Normalize lots to bricklink-compatible output
        results = []
        for lot in matching:
            lot_dict = lot.model_dump(mode="json")
            qty = int(lot.qty or 0)
            if qty <= 0:
                continue

            # Parse color_id from BOID suffix
            boid_parts = (lot.boid or "").split("-")
            bo_color_id = boid_parts[1] if len(boid_parts) > 1 else None

            # Optionally filter by color_id
            if color_id is not None and str(bo_color_id) != str(color_id):
                continue

            # Get design_id from ids dict (extra field from API)
            ids = lot_dict.get("ids", {})
            design_id = ids.get("design_id") if isinstance(ids, dict) else None

            # Get BL lot ID cross-reference from external_lot_ids
            ext_lot_ids = lot_dict.get("external_lot_ids", {})
            bl_lot_id = ext_lot_ids.get("other") if isinstance(ext_lot_ids, dict) else None

            # Resolve color name (prefer lot's own color_name, fall back to map)
            color_name = lot.color_name or color_map.get(str(bo_color_id), str(bo_color_id))

            # Map condition to N/U
            con = lot.condition or ""
            new_or_used = "N" if con.startswith("new") else "U"

            results.append({
                "lot_id": lot.lot_id,
                "inventory_id": bl_lot_id,
                "color_id": int(bo_color_id) if bo_color_id and bo_color_id.isdigit() else bo_color_id,
                "color_name": color_name,
                "quantity": qty,
                "unit_price": lot.price,
                "remarks": lot.personal_note,
                "new_or_used": new_or_used,
                "item": {"no": design_id or part_no},
            })

        return {"results": results}

    def update_inventory(
        self,
        lot_id: Optional[str] = None,
        external_id: Optional[str] = None,
        absolute_quantity: Optional[int] = None,
        relative_quantity: Optional[int] = None,
        price: Optional[float] = None,
        for_sale: Optional[bool] = None,
        sale_percent: Optional[int] = None,
        condition: Optional[str] = None,
        personal_note: Optional[str] = None,
        public_note: Optional[str] = None,
    ) -> Dict:
        """Update an inventory lot."""
        data: Dict[str, Any] = {}
        if lot_id:
            data["lot_id"] = lot_id
        if external_id:
            data["external_id"] = external_id
        if absolute_quantity is not None:
            data["absolute_quantity"] = absolute_quantity
        if relative_quantity is not None:
            data["relative_quantity"] = relative_quantity
        if price is not None:
            data["price"] = price
        if for_sale is not None:
            data["for_sale"] = 1 if for_sale else 0
        if sale_percent is not None:
            data["sale_percent"] = sale_percent
        if condition is not None:
            data["condition"] = condition
        if personal_note is not None:
            data["personal_note"] = personal_note
        if public_note is not None:
            data["public_note"] = public_note
        return self._post("/inventory/update", data)

    def delete_inventory(self, lot_id: Optional[str] = None, external_id: Optional[str] = None) -> Dict:
        """Delete an inventory lot."""
        data: Dict[str, Any] = {}
        if lot_id:
            data["lot_id"] = lot_id
        if external_id:
            data["external_id"] = external_id
        return self._post("/inventory/delete", data)

    @cached
    def get_inventory_stats(self) -> InventoryStats:
        """Compute inventory statistics from active lots."""
        lots = self.list_inventory(active_only=True)
        total_lots = len(lots)
        total_items = 0
        total_value = 0.0
        by_type: Dict[str, Dict[str, Any]] = {}

        for lot in lots:
            qty = int(lot.qty or 0)
            price = float(lot.price or 0)
            total_items += qty
            total_value += qty * price
            lot_type = lot.type or "Unknown"
            if lot_type not in by_type:
                by_type[lot_type] = {"lots": 0, "items": 0, "value": 0.0}
            by_type[lot_type]["lots"] += 1
            by_type[lot_type]["items"] += qty
            by_type[lot_type]["value"] += qty * price

        total_value = round(total_value, 2)
        for t in by_type:
            by_type[t]["value"] = round(by_type[t]["value"], 2)

        return InventoryStats(
            total_lots=total_lots,
            total_items=total_items,
            total_value=total_value,
            by_type=by_type,
        )

    # ==================== Catalog Methods ====================

    def catalog_lookup(self, boid: str) -> Dict:
        """Lookup item by BOID."""
        return self._get("/catalog/lookup", {"boid": boid})

    def catalog_search(self, query: str, page: int = 1) -> Dict:
        """Search the catalog."""
        return self._get("/catalog/search", {"query": query, "page": page})

    def catalog_id_lookup(self, id_value: str, item_type: str, id_type: Optional[str] = None) -> Dict:
        """Lookup by external ID."""
        # Map aliases to API-recognized id_type values
        id_type_aliases = {
            "bricklink": "bl_item_no",
        }
        if id_type:
            id_type = id_type_aliases.get(id_type, id_type)
        params: Dict[str, Any] = {"id": id_value, "type": item_type}
        if id_type:
            params["id_type"] = id_type
        return self._get("/catalog/id_lookup", params)

    def catalog_availability(self, boid: str, country: str, quantity: Optional[int] = None) -> Dict:
        """Get pricing/availability for an item."""
        params: Dict[str, Any] = {"boid": boid, "country": country}
        if quantity:
            params["quantity"] = quantity
        return self._get("/catalog/availability", params)

    def catalog_inventory(self, boid: str) -> Any:
        """Get parts in a set."""
        return self._get("/catalog/inventory", {"boid": boid})

    def catalog_colors(self) -> Any:
        """Get list of colors."""
        return self._get("/catalog/color_list")

    def catalog_conditions(self) -> Any:
        """Get list of conditions."""
        return self._get("/catalog/condition_list")

    def catalog_field_options(self, field_type: str, language: str = "en") -> Any:
        """Get field options (categories, themes, etc.)."""
        return self._get("/catalog/field_option_list", {"type": field_type, "language": language})

    # ==================== User Methods ====================

    @cached
    def get_user_details(self) -> UserDetails:
        """Get user/store details."""
        response = self._get("/user/details")
        return UserDetails(**response)

    # ==================== Browser Auth Testing ====================

    def test_auth(self) -> dict:
        """Test browser authentication status.

        Returns:
            Dict with authenticated, url, cookies, and details.
        """
        from .config import get_config
        config = get_config()
        browser = config.get_browser()
        try:
            return browser.test_session()
        finally:
            browser.close()


# Module-level client instance - singleton pattern
_client: Optional[BrickowlClient] = None


def get_client() -> BrickowlClient:
    """Get or create the global Brick Owl client instance."""
    global _client
    if _client is None:
        _client = BrickowlClient()
    return _client
