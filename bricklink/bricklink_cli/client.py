"""Bricklink API client with OAuth 1.0a authentication and exponential retry."""
import random
import time
from typing import Any, Dict, List, Optional, Union

import requests
from requests_oauthlib import OAuth1Session

from .config import get_config
from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.data_cache import cached

activity = get_activity_logger("bricklink")


# Retry configuration defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_JITTER = 0.1  # 10% jitter

# HTTP status codes that trigger retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Bricklink meta.code values that indicate success
SUCCESS_CODES = {200, 201, 204}


class BricklinkClient:
    """Client for the Bricklink REST API using OAuth 1.0a (HMAC-SHA1)."""

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        """Initialize the Bricklink client from configuration.

        Args:
            max_retries: Maximum number of retry attempts for transient errors.
            base_delay: Base delay in seconds for exponential backoff.
            max_delay: Maximum delay in seconds between retries.
            jitter: Random jitter factor to prevent thundering herd.
        """
        self.config = get_config()

        if not self.config.has_api_credentials():
            activity.error("Missing API credentials — cannot create OAuth1 session")
            raise ClientError(
                "Missing Bricklink API credentials. "
                "Set CLIENT_ID, CLIENT_SECRET, ACCESS_TOKEN, and REFRESH_TOKEN "
                "in .env (maps to OAuth 1.0a consumer key/secret + token value/secret)."
            )

        self.base_url = self.config.base_url
        self.session = OAuth1Session(
            client_key=self.config.consumer_key,
            client_secret=self.config.consumer_secret,
            resource_owner_key=self.config.token_value,
            resource_owner_secret=self.config.token_secret,
        )
        activity.info("OAuth1 session created for base_url=%s", self.base_url)

        # Retry configuration
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

    # ==================== Request Infrastructure ====================

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """Calculate delay using exponential backoff with jitter.

        Args:
            attempt: Current retry attempt number (0-indexed).
            retry_after: Optional Retry-After header value from server.

        Returns:
            Delay in seconds before next retry.
        """
        if retry_after is not None:
            return min(retry_after, self.max_delay)

        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        delay += random.uniform(-jitter_range, jitter_range)
        return min(delay, self.max_delay)

    def _is_retryable(self, response: Optional[requests.Response], exception: Optional[Exception]) -> bool:
        """Determine if a request should be retried.

        Args:
            response: Response object (if request completed).
            exception: Exception raised (if request failed).

        Returns:
            True if request should be retried.
        """
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
        """Extract Retry-After header value from response.

        Args:
            response: Response object.

        Returns:
            Retry delay in seconds, or None if not present.
        """
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return None
        try:
            return float(retry_after)
        except ValueError:
            return None

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Union[Dict, List]] = None,
        params: Optional[Dict] = None,
        retry: bool = True,
    ) -> Any:
        """Make an HTTP request to the Bricklink API with exponential retry.

        Bricklink wraps all responses in {"meta": {"code": ...}, "data": ...}.
        This method extracts and returns only the "data" payload.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE).
            endpoint: API endpoint path (e.g., "/orders").
            data: Request body data (dict or list).
            params: Query parameters.
            retry: Whether to retry on transient errors.

        Returns:
            The "data" payload from the Bricklink response (dict or list).

        Raises:
            ClientError: If request fails after all retries or API returns an error.
        """
        url = f"{self.base_url}{endpoint}"
        activity.info("%s %s", method, endpoint)

        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None
        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    json=data,
                    params=params,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )
                last_response = response

                # Check if we should retry this response
                if retry and self._is_retryable(response, None) and attempt < self.max_retries:
                    retry_after = self._get_retry_after(response)
                    delay = self._calculate_retry_delay(attempt, retry_after)
                    activity.warning("%s %s -> %d, retrying (attempt %d, delay %.1fs)",
                                     method, endpoint, response.status_code, attempt + 1, delay)
                    time.sleep(delay)
                    continue

                break

            except requests.exceptions.RequestException as e:
                last_exception = e
                if retry and self._is_retryable(None, e) and attempt < self.max_retries:
                    delay = self._calculate_retry_delay(attempt)
                    activity.warning("%s %s failed: %s, retrying (attempt %d, delay %.1fs)",
                                     method, endpoint, e, attempt + 1, delay)
                    time.sleep(delay)
                    continue
                break

        # Handle the final result
        if last_exception is not None and last_response is None:
            activity.error("%s %s failed after %d attempts: %s", method, endpoint, attempt + 1, last_exception)
            raise ClientError(f"Request failed after {attempt + 1} attempts: {last_exception}")

        if last_response is None:
            activity.error("%s %s failed: no response received", method, endpoint)
            raise ClientError("Request failed: no response received")

        # Handle HTTP-level errors (before we can parse meta)
        if last_response.status_code in RETRYABLE_STATUS_CODES or last_response.status_code >= 400:
            # Try to parse Bricklink error envelope
            try:
                body = last_response.json()
                meta = body.get("meta", {})
                description = meta.get("description", meta.get("message", ""))
                if description:
                    activity.error("%s %s -> %d: %s", method, endpoint, last_response.status_code, description)
                    raise ClientError(f"Bricklink API error {meta.get('code', last_response.status_code)}: {description}")
            except (ValueError, AttributeError):
                pass
            activity.error("%s %s -> HTTP %d", method, endpoint, last_response.status_code)
            raise ClientError(f"HTTP {last_response.status_code}: {last_response.text[:500]}")

        # Handle 204 No Content
        if last_response.status_code == 204:
            return {}

        # Parse the Bricklink response envelope
        try:
            body = last_response.json()
        except ValueError:
            raise ClientError(f"Invalid JSON response: {last_response.text[:500]}")

        meta = body.get("meta", {})
        meta_code = meta.get("code")

        # Check meta.code for API-level errors
        if meta_code not in SUCCESS_CODES:
            description = meta.get("description", meta.get("message", "Unknown error"))
            activity.error("%s %s -> meta.code %s: %s", method, endpoint, meta_code, description)
            raise ClientError(f"Bricklink API error {meta_code}: {description}")

        activity.info("%s %s -> %d", method, endpoint, last_response.status_code)
        # Return the data payload
        return body.get("data", {})

    def test_connection(self) -> None:
        """Perform an uncached lightweight API read for auth verification."""
        self._make_request("GET", "/orders", params={"direction": "in"})

    # ==================== Order Methods ====================

    @cached
    def list_orders(
        self,
        direction: Optional[str] = None,
        status: Optional[str] = None,
        filed: Optional[bool] = None,
    ) -> List[Dict]:
        """List orders.

        Args:
            direction: "in" (received) or "out" (placed).
            status: Comma-separated status values to filter by.
            filed: True for filed orders only, False for unfiled only.

        Returns:
            List of order dicts.
        """
        params: Dict[str, Any] = {}
        if direction is not None:
            params["direction"] = direction
        if status is not None:
            params["status"] = status
        if filed is not None:
            params["filed"] = "true" if filed else "false"

        result = self._make_request("GET", "/orders", params=params)
        return result if isinstance(result, list) else []

    @cached
    def get_order(self, order_id: Union[str, int]) -> Dict:
        """Get full order details.

        Args:
            order_id: The Bricklink order ID.

        Returns:
            Order detail dict.
        """
        return self._make_request("GET", f"/orders/{order_id}")

    @cached
    def get_order_items(self, order_id: Union[str, int]) -> List:
        """Get items in an order.

        Args:
            order_id: The Bricklink order ID.

        Returns:
            List of order item batch lists.
        """
        result = self._make_request("GET", f"/orders/{order_id}/items")
        return result if isinstance(result, list) else []

    @cached
    def get_order_messages(self, order_id: Union[str, int]) -> List[Dict]:
        """Get messages for an order.

        Args:
            order_id: The Bricklink order ID.

        Returns:
            List of message dicts.
        """
        result = self._make_request("GET", f"/orders/{order_id}/messages")
        return result if isinstance(result, list) else []

    def update_order(self, order_id: Union[str, int], updates: Dict) -> Dict:
        """Update order fields (shipping, remarks, etc.).

        Args:
            order_id: The Bricklink order ID.
            updates: Dict of fields to update.

        Returns:
            Updated order dict.
        """
        return self._make_request("PUT", f"/orders/{order_id}", data=updates)

    def update_order_status(self, order_id: Union[str, int], status: str) -> Dict:
        """Update the status of an order.

        Args:
            order_id: The Bricklink order ID.
            status: New status value (e.g., "PACKED", "SHIPPED", "COMPLETED").

        Returns:
            Result dict.
        """
        return self._make_request(
            "PUT",
            f"/orders/{order_id}/status",
            data={"field": "status", "value": status},
        )

    def mark_shipped(
        self,
        order_id: Union[str, int],
        tracking_no: Optional[str] = None,
        tracking_link: Optional[str] = None,
    ) -> Dict:
        """Mark an order as shipped, optionally with tracking info.

        Updates shipping details first (if provided), then sets status to SHIPPED.

        Args:
            order_id: The Bricklink order ID.
            tracking_no: Optional tracking number.
            tracking_link: Optional tracking URL.

        Returns:
            Result dict from the status update.
        """
        if tracking_no or tracking_link:
            shipping_updates: Dict[str, Any] = {}
            if tracking_no:
                shipping_updates["tracking_no"] = tracking_no
            if tracking_link:
                shipping_updates["tracking_link"] = tracking_link
            shipping_updates["date_shipped"] = _utc_now_iso()
            self.update_order(order_id, {"shipping": shipping_updates})

        return self.update_order_status(order_id, "SHIPPED")

    def file_order(self, order_id: Union[str, int]) -> Dict:
        """File an order (set is_filed to true).

        Args:
            order_id: The Bricklink order ID.

        Returns:
            Updated order dict.
        """
        return self.update_order(order_id, {"is_filed": True})

    # ==================== Inventory Methods ====================

    @cached
    def list_inventories(
        self,
        item_type: Optional[str] = None,
        status: Optional[str] = None,
        category_id: Optional[int] = None,
        color_id: Optional[int] = None,
    ) -> List[Dict]:
        """List store inventories.

        Args:
            item_type: Filter by item type (e.g., "PART", "SET", "MINIFIG").
            status: Filter by status (e.g., "Y" for available, "S" for stockroom).
            category_id: Filter by category ID.
            color_id: Filter by color ID.

        Returns:
            List of inventory dicts.
        """
        params: Dict[str, Any] = {}
        if item_type is not None:
            params["item_type"] = item_type
        if status is not None:
            params["status"] = status
        if category_id is not None:
            params["category_id"] = category_id
        if color_id is not None:
            params["color_id"] = color_id

        result = self._make_request("GET", "/inventories", params=params)
        return result if isinstance(result, list) else []

    @cached
    def get_inventory(self, inventory_id: Union[str, int]) -> Dict:
        """Get a specific inventory item.

        Args:
            inventory_id: The inventory ID.

        Returns:
            Inventory dict.
        """
        return self._make_request("GET", f"/inventories/{inventory_id}")

    def create_inventory(self, inventory_data: List[Dict]) -> Any:
        """Create new inventory entries.

        Args:
            inventory_data: List of inventory item dicts to create. The Bricklink
                API expects an array body for batch creation.

        Returns:
            Response data (may be empty on success).
        """
        return self._make_request("POST", "/inventories", data=inventory_data)

    def update_inventory(self, inventory_id: Union[str, int], updates: Dict) -> Dict:
        """Update an inventory item.

        When the update would result in 0 quantity and no stockroom is specified,
        automatically moves the item to stockroom A to avoid the Bricklink API
        error: "Update would result in 0 quantity without being in stockroom".

        Args:
            inventory_id: The inventory ID.
            updates: Dict of fields to update (quantity, price, description, etc.).

        Returns:
            Updated inventory dict.
        """
        try:
            return self._make_request("PUT", f"/inventories/{inventory_id}", data=updates)
        except ClientError as e:
            if "0 quantity" in str(e) and "stockroom" in str(e):
                activity.info(
                    "Quantity for inventory %s would become 0; auto-setting stockroom A",
                    inventory_id,
                )
                updates = dict(updates)  # avoid mutating caller's dict
                updates["is_stock_room"] = True
                updates["stock_room_id"] = "A"
                return self._make_request("PUT", f"/inventories/{inventory_id}", data=updates)
            raise

    def delete_inventory(self, inventory_id: Union[str, int]) -> Dict:
        """Delete an inventory item.

        Args:
            inventory_id: The inventory ID.

        Returns:
            Empty dict on success.
        """
        return self._make_request("DELETE", f"/inventories/{inventory_id}")

    # ==================== Catalog Methods ====================

    @cached
    def get_catalog_item(self, item_type: str, item_no: str) -> Dict:
        """Get catalog information for an item.

        Args:
            item_type: Item type (PART, SET, MINIFIG, BOOK, GEAR, CATALOG, INSTRUCTION, UNSORTED_LOT, ORIGINAL_BOX).
            item_no: Item number (e.g., "3001", "75192-1").

        Returns:
            Catalog item dict.
        """
        return self._make_request("GET", f"/items/{item_type}/{item_no}")

    @cached
    def get_price_guide(
        self,
        item_type: str,
        item_no: str,
        color_id: Optional[int] = None,
        guide_type: Optional[str] = None,
        condition: Optional[str] = None,
        country_code: Optional[str] = None,
        region: Optional[str] = None,
        currency_code: Optional[str] = None,
        vat: Optional[str] = None,
    ) -> Dict:
        """Get price guide for an item.

        Args:
            item_type: Item type (e.g., "PART", "SET").
            item_no: Item number.
            color_id: Color ID to filter by.
            guide_type: "sold" or "stock" (default: "stock").
            condition: "N" (new) or "U" (used).
            country_code: Two-letter country code.
            region: Region (e.g., "north_america", "europe", "asia").
            currency_code: Three-letter currency code.
            vat: VAT option ("N" no, "Y" yes, "O" as Norway).

        Returns:
            Price guide dict.
        """
        params: Dict[str, Any] = {}
        if color_id is not None:
            params["color_id"] = color_id
        if guide_type is not None:
            params["guide_type"] = guide_type
        if condition is not None:
            params["new_or_used"] = condition
        if country_code is not None:
            params["country_code"] = country_code
        if region is not None:
            params["region"] = region
        if currency_code is not None:
            params["currency_code"] = currency_code
        if vat is not None:
            params["vat"] = vat

        return self._make_request("GET", f"/items/{item_type}/{item_no}/price", params=params)

    @cached
    def get_known_colors(self, item_type: str, item_no: str) -> List[Dict]:
        """Get known colors for an item.

        Args:
            item_type: Item type.
            item_no: Item number.

        Returns:
            List of color dicts with quantity info.
        """
        result = self._make_request("GET", f"/items/{item_type}/{item_no}/colors")
        return result if isinstance(result, list) else []

    @cached
    def get_colors(self) -> List[Dict]:
        """Get all colors defined in BrickLink catalog."""
        result = self._make_request("GET", "/colors")
        return result if isinstance(result, list) else []

    @cached
    def get_color(self, color_id: int) -> Dict:
        """Get a specific color by ID."""
        return self._make_request("GET", f"/colors/{color_id}")

    @cached
    def get_subsets(
        self,
        item_type: str,
        item_no: str,
        color_id: Optional[int] = None,
        break_minifigs: Optional[bool] = None,
        break_subsets: Optional[bool] = None,
    ) -> List[Dict]:
        """Get subsets (parts/contents) of an item.

        Args:
            item_type: Item type.
            item_no: Item number.
            color_id: Color ID (for parts in a specific color).
            break_minifigs: Whether to break down minifigs into parts.
            break_subsets: Whether to break down subsets recursively.

        Returns:
            List of subset entry dicts.
        """
        params: Dict[str, Any] = {}
        if color_id is not None:
            params["color_id"] = color_id
        if break_minifigs is not None:
            params["break_minifigs"] = "true" if break_minifigs else "false"
        if break_subsets is not None:
            params["break_subsets"] = "true" if break_subsets else "false"

        result = self._make_request("GET", f"/items/{item_type}/{item_no}/subsets", params=params)
        return result if isinstance(result, list) else []

    @cached
    def get_supersets(
        self,
        item_type: str,
        item_no: str,
        color_id: Optional[int] = None,
    ) -> List[Dict]:
        """Get supersets (items that contain this item).

        Args:
            item_type: Item type.
            item_no: Item number.
            color_id: Color ID.

        Returns:
            List of superset entry dicts.
        """
        params: Dict[str, Any] = {}
        if color_id is not None:
            params["color_id"] = color_id

        result = self._make_request("GET", f"/items/{item_type}/{item_no}/supersets", params=params)
        return result if isinstance(result, list) else []

    # ==================== Member Methods ====================

    @cached
    def get_member_ratings(self, username: str) -> Dict:
        """Get member feedback/ratings.

        Args:
            username: Bricklink username.

        Returns:
            Ratings dict.
        """
        return self._make_request("GET", f"/members/{username}/ratings")

    @cached
    def get_member_note(self, username: str) -> Dict:
        """Get personal note for a member.

        Args:
            username: Bricklink username.

        Returns:
            Note dict (or empty dict if no note).
        """
        return self._make_request("GET", f"/members/{username}/notes")

    def set_member_note(self, username: str, text: str) -> Dict:
        """Create or update a personal note for a member.

        Uses POST to create if no note exists, PUT to update.
        Falls back to the other method if one fails.

        Args:
            username: Bricklink username.
            text: Note text to set.

        Returns:
            Note dict.
        """
        try:
            return self._make_request(
                "POST",
                f"/members/{username}/notes",
                data={"note_text": text},
            )
        except ClientError:
            # If POST fails (note already exists), try PUT
            return self._make_request(
                "PUT",
                f"/members/{username}/notes",
                data={"note_text": text},
            )

    def delete_member_note(self, username: str) -> Dict:
        """Delete personal note for a member.

        Args:
            username: Bricklink username.

        Returns:
            Empty dict on success.
        """
        return self._make_request("DELETE", f"/members/{username}/notes")

    # ==================== Coupon Methods ====================

    @cached
    def list_coupons(
        self,
        direction: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict]:
        """List coupons.

        Args:
            direction: "out" (issued) or "in" (received).
            status: Filter by status ("O" open, "S" redeemed, "D" denied, "X" expired).

        Returns:
            List of coupon dicts.
        """
        params: Dict[str, Any] = {}
        if direction is not None:
            params["direction"] = direction
        if status is not None:
            params["status"] = status

        result = self._make_request("GET", "/coupons", params=params)
        return result if isinstance(result, list) else []

    @cached
    def get_coupon(self, coupon_id: Union[str, int]) -> Dict:
        """Get details for a specific coupon.

        Args:
            coupon_id: The coupon ID.

        Returns:
            Coupon detail dict.
        """
        return self._make_request("GET", f"/coupons/{coupon_id}")

    def create_coupon(self, data: Dict) -> Dict:
        """Create a new coupon.

        Args:
            data: Coupon data dict (coupon_type, discount_type, discount_rate,
                  max_discount_amount, expires_date, buyer_name, etc.).

        Returns:
            Created coupon dict.
        """
        return self._make_request("POST", "/coupons", data=data)

    def delete_coupon(self, coupon_id: Union[str, int]) -> Dict:
        """Delete a coupon.

        Args:
            coupon_id: The coupon ID.

        Returns:
            Empty dict on success.
        """
        return self._make_request("DELETE", f"/coupons/{coupon_id}")

    def test_auth(self) -> dict:
        """Test browser authentication status via the configured browser."""
        activity.info("Testing browser auth session")
        browser = get_config().get_browser()
        result = browser.test_session()
        activity.info("Browser auth test result: authenticated=%s", result.get("authenticated"))
        return result

# ==================== Helpers ====================

def _utc_now_iso() -> str:
    """Return current UTC time in ISO 8601 format for the Bricklink API."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ==================== Singleton ====================

_client: Optional[BricklinkClient] = None


def get_client() -> BricklinkClient:
    """Get or create the global Bricklink client instance."""
    global _client
    if _client is None:
        _client = BricklinkClient()
    return _client
