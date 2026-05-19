"""Brick Owl domain models.

Models for orders, inventory lots, catalog items, messages, refunds, coupons, and quotes.
"""
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import Field

from cli_tools_shared.models import CLIModel


# ==================== Enums ====================


class OrderStatus(int, Enum):
    """Brick Owl order status IDs."""
    PENDING = 0
    PAYMENT_SUBMITTED = 1
    PAYMENT_RECEIVED = 2
    PROCESSING = 3
    PROCESSED = 4
    SHIPPED = 5
    RECEIVED = 6
    ON_HOLD = 7
    CANCELLED = 8


ORDER_STATUS_NAMES = {
    0: "Pending",
    1: "Payment Submitted",
    2: "Payment Received",
    3: "Processing",
    4: "Processed",
    5: "Shipped",
    6: "Received",
    7: "On Hold",
    8: "Cancelled",
}

NOT_SHIPPED_STATUSES = [0, 1, 2, 3, 4]
NOT_PICKED_STATUSES = [0, 1, 2, 3]


class ItemType(str, Enum):
    """Brick Owl catalog item types."""
    PART = "Part"
    SET = "Set"
    MINIFIGURE = "Minifigure"
    GEAR = "Gear"
    STICKER = "Sticker"
    MINIBUILD = "Minibuild"
    INSTRUCTIONS = "Instructions"
    PACKAGING = "Packaging"


class Condition(str, Enum):
    """Brick Owl condition codes."""
    NEW = "new"
    NEW_SEALED = "news"
    NEW_COMPLETE = "newc"
    NEW_INCOMPLETE = "newi"
    USED_COMPLETE = "usedc"
    USED_INCOMPLETE = "usedi"
    USED_LIKE_NEW = "usedn"
    USED_GOOD = "usedg"
    USED_ACCEPTABLE = "useda"
    OTHER = "other"


class CouponType(str, Enum):
    """Coupon types."""
    CODE = "code"
    USER = "user"


class RefundReason(str, Enum):
    """Refund reason codes (match dropdown labels on refund page)."""
    MISSING_ITEMS = "Missing items"
    OVERCHARGED_SHIPPING = "Overcharged shipping"
    CANCEL_ORDER = "Buyer and Seller agreed to cancel order"
    CANNOT_COMPLETE = "Seller cannot complete transaction"
    INCORRECT_AMOUNT = "Buyer paid incorrect amount"


class FeedbackRating(int, Enum):
    """Feedback rating values."""
    POSITIVE = 1
    NEUTRAL = 0
    NEGATIVE = -1


# ==================== Order Models ====================


class Order(CLIModel):
    """Order from the Brick Owl API list endpoint.

    The API returns varying fields. We accept everything via extra="ignore"
    and define the commonly returned fields.
    """
    order_id: str
    order_date: Optional[str] = None
    status_id: Optional[int] = None
    status: Optional[str] = None
    total_quantity: Optional[str] = None
    total_lots: Optional[str] = None
    base_order_total: Optional[str] = None
    buyer_name: Optional[str] = None
    buyer_username: Optional[str] = None
    ship_method_name: Optional[str] = None
    tracking_id: Optional[str] = None
    weight: Optional[str] = None
    note: Optional[str] = None
    # Computed field
    shipped: Optional[bool] = None

    model_config = CLIModel.model_config.copy()
    model_config["extra"] = "allow"


class OrderDetail(CLIModel):
    """Detailed order info from /order/view endpoint."""
    order_id: str

    model_config = CLIModel.model_config.copy()
    model_config["extra"] = "allow"


class OrderItem(CLIModel):
    """An item within an order."""
    boid: Optional[str] = None
    lot_id: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    color: Optional[str] = None
    ordered_quantity: Optional[str] = None
    base_price: Optional[str] = None
    condition: Optional[str] = None
    image_small: Optional[str] = None

    model_config = CLIModel.model_config.copy()
    model_config["extra"] = "allow"


# ==================== Inventory Models ====================


class InventoryLot(CLIModel):
    """An inventory lot from the Brick Owl API."""
    lot_id: Optional[str] = None
    boid: Optional[str] = None
    type: Optional[str] = None
    name: Optional[str] = None
    qty: Optional[str] = None
    price: Optional[str] = None
    condition: Optional[str] = None
    color_name: Optional[str] = None
    color_id: Optional[str] = None
    for_sale: Optional[int] = None
    personal_note: Optional[str] = None
    public_note: Optional[str] = None
    sale_percent: Optional[str] = None
    tier_price: Optional[Any] = None
    external_id_1: Optional[str] = None
    external_id_2: Optional[str] = None
    weight: Optional[str] = None
    image_small: Optional[str] = None

    model_config = CLIModel.model_config.copy()
    model_config["extra"] = "allow"


class InventoryStats(CLIModel):
    """Computed inventory statistics."""
    total_lots: int
    total_items: int
    total_value: float
    by_type: Dict[str, Any] = {}


# ==================== Catalog Models ====================


class CatalogItem(CLIModel):
    """A catalog item from lookup/search."""
    boid: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    category_name: Optional[str] = None
    image_small: Optional[str] = None

    model_config = CLIModel.model_config.copy()
    model_config["extra"] = "allow"


class CatalogSearchResult(CLIModel):
    """Search results wrapper."""
    rows: Optional[List[Dict[str, Any]]] = None
    total: Optional[int] = None

    model_config = CLIModel.model_config.copy()
    model_config["extra"] = "allow"


class CatalogIdLookup(CLIModel):
    """Result of an ID lookup."""
    boids: Optional[List[str]] = None

    model_config = CLIModel.model_config.copy()
    model_config["extra"] = "allow"


class Color(CLIModel):
    """A color definition."""
    color_id: Optional[str] = None
    name: Optional[str] = None
    hex: Optional[str] = None

    model_config = CLIModel.model_config.copy()
    model_config["extra"] = "allow"


# ==================== User Models ====================


class UserDetails(CLIModel):
    """User/store details."""
    user_id: Optional[str] = None
    username: Optional[str] = None
    store_name: Optional[str] = None

    model_config = CLIModel.model_config.copy()
    model_config["extra"] = "allow"


# ==================== Browser Automation Models ====================


class Message(CLIModel):
    """Brickowl message (browser-scraped)."""
    message_id: Optional[str] = None
    subject: Optional[str] = None
    from_username: Optional[str] = Field(default=None, alias="from")
    to_username: Optional[str] = Field(default=None, alias="to")
    sent_date: Optional[str] = None
    body: Optional[str] = None
    order_id: Optional[str] = None
    is_unread: Optional[bool] = None
    url: Optional[str] = None
    reply_url: Optional[str] = None
    attachments: Optional[List[Dict[str, Any]]] = None
    message_history: Optional[list] = None
    source: Optional[str] = None

    model_config = CLIModel.model_config.copy()
    model_config["extra"] = "allow"


class RefundInfo(CLIModel):
    """Refund information for an order."""
    order_id: str
    order_total: Optional[str] = None
    prior_refunds: Optional[List[Dict[str, Any]]] = None
    prior_refund_total: Optional[str] = None
    max_refund: Optional[str] = None

    model_config = CLIModel.model_config.copy()
    model_config["extra"] = "allow"


class RefundResult(CLIModel):
    """Result of a refund operation."""
    success: bool
    order_id: str
    amount: Optional[str] = None
    reason: Optional[str] = None
    message: Optional[str] = None


class Coupon(CLIModel):
    """A store coupon."""
    coupon_id: Optional[str] = None
    code: Optional[str] = None
    coupon_type: Optional[str] = None
    note: Optional[str] = None
    discount: Optional[str] = None
    min_order: Optional[str] = None
    max_discount: Optional[str] = None
    free_shipping: Optional[bool] = None
    enabled: Optional[bool] = None
    redeemed: Optional[int] = None
    limit: Optional[int] = None
    username: Optional[str] = None

    model_config = CLIModel.model_config.copy()
    model_config["extra"] = "allow"


class Quote(CLIModel):
    """A quote request from list view."""
    quote_id: Optional[str] = None
    date: Optional[str] = None
    buyer: Optional[Dict[str, Any]] = None
    items: Optional[int] = None
    lots: Optional[int] = None
    total: Optional[str] = None
    status: Optional[str] = None
    url: Optional[str] = None

    model_config = CLIModel.model_config.copy()
    model_config["extra"] = "allow"


class QuoteDetail(CLIModel):
    """Detailed quote information from detail page."""
    quote_id: Optional[str] = None
    date: Optional[str] = None
    buyer: Optional[Dict[str, Any]] = None
    items: Optional[str] = None
    weight: Optional[str] = None
    subtotal: Optional[str] = None
    shipping: Optional[str] = None
    tax: Optional[str] = None
    total: Optional[str] = None
    customer_info: Optional[Dict[str, Any]] = None
    shipping_address: Optional[Dict[str, Any]] = None
    line_items: Optional[List[Dict[str, Any]]] = None
    url: Optional[str] = None

    model_config = CLIModel.model_config.copy()
    model_config["extra"] = "allow"


class MessageActionResult(CLIModel):
    """Result of a message action (reply, send, mark-read, mark-unread)."""
    success: bool
    message_id: Optional[str] = None
    recipient: Optional[str] = None
    action: Optional[str] = None
    message: Optional[str] = None

    model_config = CLIModel.model_config.copy()
    model_config["extra"] = "allow"


class CouponActionResult(CLIModel):
    """Result of a coupon action (create, delete)."""
    success: bool
    coupon_type: Optional[str] = None
    username: Optional[str] = None
    code: Optional[str] = None
    coupon_id: Optional[str] = None
    message: Optional[str] = None

    model_config = CLIModel.model_config.copy()
    model_config["extra"] = "allow"


class OrderInfo(CLIModel):
    """Order info scraped from the order history page."""
    order_id: str
    order_total: Optional[str] = None
    buyer_name: Optional[str] = None
    status: Optional[str] = None
    payment_amount: Optional[str] = None
    transaction_id: Optional[str] = None

    model_config = CLIModel.model_config.copy()
    model_config["extra"] = "allow"


# ==================== Helper Functions ====================


def resolve_status(status: str) -> int:
    """Resolve a status name to its numeric ID.

    Args:
        status: Status name or numeric ID string

    Returns:
        Numeric status ID
    """
    try:
        return int(status)
    except ValueError:
        pass

    status_map = {
        "pending": 0,
        "payment submitted": 1,
        "payment received": 2,
        "processing": 3,
        "processed": 4,
        "shipped": 5,
        "received": 6,
        "on hold": 7,
        "cancelled": 8,
    }
    normalized = status.lower().strip()
    if normalized in status_map:
        return status_map[normalized]
    raise ValueError(f"Unknown status: {status}")


def is_shipped_status(status_id: int) -> bool:
    """Check if an order status is considered shipped."""
    return status_id not in NOT_SHIPPED_STATUSES


def is_not_picked_status(status_id: int) -> bool:
    """Check if an order status is considered not picked."""
    return status_id in NOT_PICKED_STATUSES
