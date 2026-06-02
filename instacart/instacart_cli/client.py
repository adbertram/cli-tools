"""Instacart GraphQL API client using browser session cookies."""
from typing import Any, Dict, List, Optional
import random
import time
import warnings

warnings.filterwarnings("ignore", module="urllib3")

import requests

from .config import get_config
from .models import Order, OrderDetail, create_order, create_order_detail


# Retry configuration defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_JITTER = 0.1  # 10% jitter

# HTTP status codes that trigger retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ClientError(Exception):
    """Custom exception for Instacart API errors."""
    pass


class InstacartClient:
    """Client for interacting with Instacart GraphQL API using browser session."""

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
        config=None,
    ):
        """
        Initialize Instacart client from session configuration.

        Args:
            max_retries: Maximum number of retry attempts for transient errors (default: 3)
            base_delay: Base delay in seconds for exponential backoff (default: 1.0)
            max_delay: Maximum delay in seconds between retries (default: 30.0)
            jitter: Random jitter factor to prevent thundering herd (default: 0.1)
        """
        self.config = config or get_config()

        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'instacart auth login' to capture browser session."
            )

        if self.config.is_session_expired():
            raise ClientError(
                "Session has expired. Run 'instacart auth login' to refresh."
            )

        self.graphql_url = self.config.graphql_endpoint
        self.persisted_queries = self.config.persisted_queries
        self._update_headers()

        # Retry configuration
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

    def _update_headers(self):
        """Update request headers with current cookies and browser-like headers."""
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Cookie": self.config.get_cookie_header(),
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Origin": "https://www.instacart.com",
            "Referer": "https://www.instacart.com/",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """
        Calculate delay before next retry using exponential backoff with jitter.

        Args:
            attempt: Current retry attempt number (0-indexed)
            retry_after: Optional Retry-After header value from server

        Returns:
            Delay in seconds before next retry
        """
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

    def _get_retry_after(self, response: requests.Response) -> Optional[float]:
        """Extract Retry-After header value from response."""
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return None
        try:
            return float(retry_after)
        except ValueError:
            return None

    def _graphql_request(
        self,
        operation_name: str,
        variables: Optional[Dict[str, Any]] = None,
        retry: bool = True,
    ) -> Dict[str, Any]:
        """
        Make a GraphQL request using persisted queries.

        Args:
            operation_name: Name of the GraphQL operation (e.g., "OrderDeliveriesConnection")
            variables: Variables to pass to the query
            retry: Whether to retry on transient errors

        Returns:
            GraphQL response data

        Raises:
            ClientError: If request fails after all retries
        """
        # Get persisted query info
        query_info = self.persisted_queries.get(operation_name)
        if not query_info:
            raise ClientError(f"Unknown operation: {operation_name}. Available: {list(self.persisted_queries.keys())}")

        sha256_hash = query_info["sha256Hash"]

        # Merge default variables with provided ones
        merged_vars = dict(query_info.get("variables", {}))
        if variables:
            merged_vars.update(variables)

        # Build GraphQL request body with persisted query extension
        payload = {
            "operationName": operation_name,
            "variables": merged_vars,
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": sha256_hash
                }
            }
        }

        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None
        max_attempts = (self.max_retries + 1) if retry else 1

        for attempt in range(max_attempts):
            try:
                response = requests.post(
                    self.graphql_url,
                    headers=self.headers,
                    json=payload,
                )
                last_response = response

                # Check for retryable status codes
                if retry and self._is_retryable(response, None) and attempt < self.max_retries:
                    retry_after = self._get_retry_after(response)
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
            raise ClientError(f"Request failed after {attempt + 1} attempts: {last_exception}")

        if last_response is None:
            raise ClientError("Request failed: no response received")

        if not last_response.ok:
            try:
                error_data = last_response.json()
                if "errors" in error_data:
                    errors = error_data["errors"]
                    error_msgs = [e.get("message", str(e)) for e in errors]
                    raise ClientError(f"GraphQL errors: {'; '.join(error_msgs)}")
                error_msg = error_data.get("message") or last_response.text
            except Exception:
                error_msg = last_response.text
            raise ClientError(f"API request failed ({last_response.status_code}): {error_msg}")

        result = last_response.json()

        # Check for GraphQL errors in successful response
        if "errors" in result and result["errors"]:
            errors = result["errors"]
            error_msgs = [e.get("message", str(e)) for e in errors]
            raise ClientError(f"GraphQL errors: {'; '.join(error_msgs)}")

        return result.get("data", result)

    # ==================== Order API Methods ====================

    def list_orders(
        self,
        limit: int = 50,
        offset: int = 0,
        filters: Optional[List[str]] = None,
    ) -> List[Order]:
        """
        List orders using PersonalOrderHistory query.

        Args:
            limit: Maximum number of orders to return
            offset: Number of orders to skip for pagination
            filters: List of filter strings (field:op:value) for client-side filtering

        Returns:
            List of Order models
        """
        from cli_tools_shared.filters import apply_filters, parse_filter_string

        variables = {"first": limit}
        data = self._graphql_request("PersonalOrderHistory", variables)

        # Extract orders from GraphQL response
        # Response structure: { orderDeliveriesConnection: { nodes: [...] } }
        nodes = []
        if isinstance(data, dict):
            connection = data.get("orderDeliveriesConnection", {})
            nodes = connection.get("nodes", connection.get("edges", []))
            # Debug: print first node to see structure
            if nodes and False:  # Set to True to debug
                import json
                print("DEBUG RAW NODE:", json.dumps(nodes[0], indent=2, default=str))

        # Transform GraphQL nodes to order dicts
        raw_orders = []
        for node in nodes:
            # Handle edge structure if present
            if "node" in node:
                node = node["node"]
            order_data = self._transform_order(node)
            raw_orders.append(order_data)

        # Convert to models
        orders = [create_order(order) for order in raw_orders]

        # Apply client-side filters if provided
        if filters:
            filter_conditions = parse_filter_string(filters)
            orders = apply_filters(orders, filter_conditions)

        return orders

    def _transform_order(self, node: Dict[str, Any]) -> Dict[str, Any]:
        """Transform GraphQL order node to standard order dict."""
        # Handle actual Instacart GraphQL response structure
        # Order ID - prefer legacyOrderId for compatibility
        order_id = node.get("legacyOrderId") or node.get("id") or node.get("orderId")

        # Extract status from workflowState
        status = node.get("workflowState") or node.get("status") or "unknown"
        if isinstance(status, dict):
            status = status.get("label") or status.get("value") or "unknown"

        # Extract timestamps
        created_at = node.get("createdAt")
        delivered_at = node.get("deliveredAt")
        updated_at = delivered_at or created_at

        # Extract total from amounts.viewSection.totalLine or fallback
        total_data = node.get("total") or node.get("orderTotal") or {}
        # Try nested amounts structure first (from PersonalOrderHistory query)
        amounts = node.get("amounts", {})
        amounts_view = amounts.get("viewSection", {})
        total_line = amounts_view.get("totalLine", {})
        amount_string = total_line.get("amountString", "")  # e.g. "$78.15"

        if amount_string:
            # Parse dollar string like "$78.15"
            try:
                total_value = float(amount_string.replace("$", "").replace(",", ""))
            except ValueError:
                total_value = 0
            total = {"value": total_value, "currency": "USD"}
        elif isinstance(total_data, dict):
            total = {
                "value": total_data.get("amount") or total_data.get("value") or 0,
                "currency": total_data.get("currency") or "USD"
            }
        else:
            total = {"value": float(total_data) if total_data else 0, "currency": "USD"}

        # Extract line items if present (from orderItems array or nested structures)
        line_items = []
        # Try orderItems array first (from PersonalOrderHistory query)
        order_items_arr = node.get("orderItems", [])
        if order_items_arr:
            for order_item in order_items_arr:
                # Each orderItem has currentItem with basketProduct
                current_item = order_item.get("currentItem", {})
                basket_product = current_item.get("basketProduct", {})
                item_info = basket_product.get("item", {})
                view_section = current_item.get("viewSection", {})

                line_items.append({
                    "line_item_id": current_item.get("id"),
                    "product": {
                        "product_id": item_info.get("productId"),
                        "name": None,  # Not available in list query
                        "price": None,
                    },
                    "quantity": 1,  # Default, actual quantity not in list query
                })
        else:
            # Fallback to older structure
            order_items = node.get("orderItemCollection", {})
            items = order_items.get("items") or node.get("items") or node.get("lineItems") or []
            for item in items:
                line_items.append(self._transform_line_item(item))

        # Extract store info from retailer
        retailer = node.get("retailer") or node.get("store") or {}
        if isinstance(retailer, dict):
            store_name = retailer.get("name") or retailer.get("retailerName")
        else:
            store_name = str(retailer) if retailer else None

        # Additional fields
        service_type = node.get("serviceType")  # delivery, pickup

        return {
            "order_id": str(order_id) if order_id else "unknown",
            "status": status,
            "created_at": created_at,
            "updated_at": updated_at,
            "delivered_at": delivered_at,
            "total": total,
            "line_items": line_items,
            "store_name": store_name,
            "service_type": service_type,
        }

    def _transform_line_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Transform GraphQL line item to standard format."""
        product = item.get("product") or item.get("item") or {}

        return {
            "line_item_id": item.get("id") or item.get("lineItemId"),
            "product": {
                "product_id": product.get("id") or product.get("productId"),
                "name": product.get("name") or product.get("displayName"),
                "price": product.get("price") or product.get("unitPrice"),
            },
            "quantity": item.get("quantity") or item.get("qty") or 1,
        }

    def get_order(self, order_id: str) -> OrderDetail:
        """
        Get a specific order by ID using PostCheckoutOrderDelivery query.

        Args:
            order_id: The order ID

        Returns:
            OrderDetail model with full details
        """
        variables = {"orderId": order_id}
        data = self._graphql_request("PostCheckoutOrderDelivery", variables)

        # Extract order from response
        order_delivery = data.get("postCheckoutOrderDelivery", data)
        order_data = self._transform_order_detail(order_delivery, order_id)

        return create_order_detail(order_data)

    def _transform_order_detail(self, node: Dict[str, Any], order_id: str) -> Dict[str, Any]:
        """Transform GraphQL order detail to standard format."""
        base = self._transform_order(node)
        base["order_id"] = order_id

        # Extract additional detail fields
        delivery_address = node.get("deliveryAddress") or node.get("address") or {}
        shopper = node.get("shopper") or node.get("shopperInfo") or {}

        base["delivery_address"] = {
            "street": delivery_address.get("street") or delivery_address.get("line1"),
            "city": delivery_address.get("city"),
            "state": delivery_address.get("state"),
            "zip_code": delivery_address.get("zipCode") or delivery_address.get("postalCode"),
        }

        base["shopper_name"] = shopper.get("name") or shopper.get("firstName")
        base["scheduled_delivery"] = node.get("scheduledDeliveryTime") or node.get("deliveryWindow")

        return base

    def create_order(self, order_data: Dict[str, Any]) -> Order:
        """
        Create a new order.

        Note: Order creation through the consumer API requires cart operations
        which may need additional persisted queries to be captured.

        Args:
            order_data: Order data with lineItems, deliveryAddress, etc.

        Returns:
            Created Order model

        Raises:
            ClientError: Order creation not yet supported
        """
        raise ClientError(
            "Order creation requires cart operations. "
            "Use the Instacart website or app to create orders, "
            "then use 'instacart orders list' to view them."
        )

    def track_order(self, order_id: str) -> Dict[str, Any]:
        """
        Get tracking information for an order.

        Args:
            order_id: The order ID

        Returns:
            Tracking information dict
        """
        order = self.get_order(order_id)

        return {
            "order_id": order.order_id,
            "status": order.status,
            "scheduled_delivery": getattr(order, "scheduled_delivery", None),
            "updated_at": order.updated_at,
            "shopper_name": getattr(order, "shopper_name", None),
            "store_name": getattr(order, "store_name", None),
        }

    def get_user(self) -> Dict[str, Any]:
        """
        Get current user information.

        Note: The persisted query only returns limited user fields.
        Additional info is extracted from session cookies.

        Returns:
            User data dict
        """
        data = self._graphql_request("CurrentUserFields")

        # Extract user from response
        user = data.get("currentUser", data)

        # Try to get email from known_visitor cookie
        email = None
        for cookie in self.config.cookies:
            if cookie.get("name") == "known_visitor":
                import urllib.parse
                value = urllib.parse.unquote(cookie.get("value", ""))
                parts = value.split("|")
                if len(parts) >= 2:
                    email = parts[1]
                break

        return {
            "user_id": user.get("id"),
            "email": email,
            "is_guest": user.get("guest", False),
            "is_admin": user.get("admin", False),
        }

    def get_addresses(self) -> List[Dict[str, Any]]:
        """
        Get user delivery addresses.

        Returns:
            List of address dicts
        """
        data = self._graphql_request("UserAddresses")

        # Extract from userAddresses (not currentUser.addresses)
        addresses = data.get("userAddresses", [])
        result = []
        for addr in addresses:
            # Parse city/state from viewSection
            view = addr.get("viewSection", {})
            city_state = view.get("cityStateString", "")
            city, state = "", ""
            if ", " in city_state:
                parts = city_state.rsplit(", ", 1)
                city, state = parts[0], parts[1]

            result.append({
                "id": addr.get("id"),
                "street": addr.get("streetAddress"),
                "apartment": addr.get("apartmentNumber"),
                "city": city,
                "state": state,
                "zip_code": addr.get("postalCode"),
                "instructions": addr.get("instructions"),
                "business_name": addr.get("businessName"),
            })
        return result

    def get_carts(self) -> List[Dict[str, Any]]:
        """
        Get active shopping carts.

        Returns:
            List of cart dicts
        """
        data = self._graphql_request("PersonalActiveCarts")

        # Response structure: { userCarts: { carts: [...] } }
        user_carts = data.get("userCarts", {})
        carts = user_carts.get("carts", [])

        result = []
        for cart in carts:
            retailer = cart.get("retailer", {})
            items = cart.get("cartItemCollection", {}).get("cartItems", [])

            result.append({
                "id": cart.get("id"),
                "retailer": retailer.get("name"),
                "item_count": cart.get("itemCount", 0),
                "items": [
                    {
                        "name": item.get("basketProduct", {}).get("name"),
                        "id": item.get("id"),
                    }
                    for item in items
                ],
            })
        return result

    def get_cart_details(self, cart_id: str) -> Dict[str, Any]:
        """
        Get detailed cart data including quantities.

        Args:
            cart_id: The cart ID

        Returns:
            Cart details with item quantities
        """
        data = self._graphql_request("CartData", {"id": cart_id})
        return data.get("userCart", {})

    def get_cart_with_prices(self, cart_id: str) -> Dict[str, Any]:
        """
        Get cart data including item prices using UserCart query.

        Args:
            cart_id: The cart ID

        Returns:
            Cart data with pricing info
        """
        data = self._graphql_request("UserCart", {"id": cart_id})
        return data.get("userCart", {})

    def get_cart_items(self, store_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all cart items with details across all stores.

        Args:
            store_filter: Optional store name to filter by

        Returns:
            List of cart items with store, name, quantity, price
        """
        # Get carts with item names from PersonalActiveCarts
        data = self._graphql_request("PersonalActiveCarts")
        user_carts = data.get("userCarts", {})
        carts = user_carts.get("carts", [])

        result = []
        for cart in carts:
            retailer = cart.get("retailer", {})
            store_name = retailer.get("name", "Unknown")

            # Apply store filter if specified
            if store_filter and store_filter.lower() not in store_name.lower():
                continue

            cart_id = cart.get("id")

            # Get cart with pricing using UserCart query
            try:
                cart_data = self.get_cart_with_prices(cart_id)
                cart_items = cart_data.get("cartItemCollection", {}).get("cartItems", [])

                for item in cart_items:
                    basket = item.get("basketProduct", {}) or {}
                    item_name = basket.get("name", "Unknown Item")

                    # Get quantity and format it
                    quantity = item.get("quantity", 1)
                    quantity_type = item.get("quantityType", "each")
                    if quantity == int(quantity):
                        qty_str = str(int(quantity))
                    else:
                        qty_str = f"{quantity:.1f}"
                    if quantity_type and quantity_type != "each":
                        qty_str = f"{qty_str} {quantity_type}"

                    # Extract price from viewSection or item pricing data
                    price_str = "-"
                    view_section = item.get("viewSection", {})
                    price_data = view_section.get("price", {})
                    if price_data:
                        # Try to get formatted price string
                        price_str = price_data.get("string") or price_data.get("displayPrice")
                        if not price_str and price_data.get("amount"):
                            price_str = f"${price_data.get('amount', 0):.2f}"

                    # Fallback to lineTotal
                    if price_str == "-":
                        line_total = view_section.get("lineTotal", {})
                        price_str = line_total.get("string") or line_total.get("displayPrice")
                        if not price_str and line_total.get("amount"):
                            price_str = f"${line_total.get('amount', 0):.2f}"

                    result.append({
                        "store": store_name,
                        "name": item_name,
                        "qty": qty_str,
                        "price": price_str or "-",
                        "item_id": item.get("id"),
                        "product_id": basket.get("productId"),
                    })
            except Exception:
                # Fallback to basic data without prices
                items_basic = cart.get("cartItemCollection", {}).get("cartItems", [])
                for item in items_basic:
                    basket = item.get("basketProduct", {})
                    result.append({
                        "store": store_name,
                        "name": basket.get("name", "Unknown Item"),
                        "qty": "1",
                        "price": "-",
                        "item_id": item.get("id"),
                        "product_id": None,
                    })

        return result


# Module-level client instance - singleton pattern
_client: Optional[InstacartClient] = None


def get_client() -> InstacartClient:
    """Get or create the global Instacart client instance."""
    global _client
    if _client is None:
        _client = InstacartClient()
    return _client
