"""Models for Brickfreedom CLI.

Defines Pydantic models for tasks, orders, missing parts, and processed orders
as scraped from the brickfreedom.com dashboard.
"""
from enum import Enum
from typing import List, Optional

from pydantic import Field

from cli_tools_shared.models import CLIModel


# ==================== Enums ====================


class Platform(str, Enum):
    """Marketplace platform."""
    BRICKLINK = "bricklink"
    BRICKOWL = "brickowl"


class OrderStatus(str, Enum):
    """Order status values from BrickFreedom."""
    # Bricklink statuses
    PAID = "PAID"
    PENDING = "PENDING"
    UPDATED = "UPDATED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"
    PURGED = "PURGED"
    # Brick Owl statuses
    PAYMENT_RECEIVED = "PAYMENT RECEIVED"
    PAYMENT_SUBMITTED = "PAYMENT SUBMITTED"


# ==================== Task Models ====================


class Task(CLIModel):
    """Task from My Tasks section on dashboard."""
    index: int = Field(frozen=True, description="1-based task index")
    text: str = Field(description="Task text/description")
    completed: bool = Field(default=False, description="Whether task is completed")


class TaskResult(CLIModel):
    """Result of a task operation."""
    success: bool
    message: str
    task: Optional[str] = None


class TaskList(CLIModel):
    """List of tasks with count."""
    tasks: List[Task]
    count: int = Field(default=0)

    def __init__(self, **data):
        if "count" not in data and "tasks" in data:
            data["count"] = len(data["tasks"])
        super().__init__(**data)


# ==================== Order Models ====================


class OrderCost(CLIModel):
    """Order cost breakdown."""
    currency_code: str = Field(default="USD")
    subtotal: str = Field(default="0.00")
    shipping: str = Field(default="0.00")
    grand_total: str = Field(default="0.00")


class Order(CLIModel):
    """Order from BrickFreedom orders page."""
    order_id: str = Field(frozen=True, description="Marketplace order ID")
    brickfreedom_id: str = Field(default="", description="BrickFreedom internal ID")
    platform: Platform = Field(description="Marketplace platform")
    date_ordered: str = Field(description="Order date")
    buyer_name: str = Field(description="Customer name")
    status: OrderStatus = Field(description="Order status")
    total_count: int = Field(default=0, description="Total item quantity")
    unique_count: int = Field(default=0, description="Number of unique lots")
    cost: OrderCost = Field(default_factory=OrderCost)
    picked: bool = Field(default=False, description="Whether order has been picked/packed")
    shipped: bool = Field(default=False, description="Whether order has been shipped")


class OrderList(CLIModel):
    """List of orders with count and page info."""
    orders: List[Order]
    count: int = Field(default=0)
    page: int = Field(default=1)

    def __init__(self, **data):
        if "count" not in data and "orders" in data:
            data["count"] = len(data["orders"])
        super().__init__(**data)


# ==================== Processed Order Models ====================


class ProcessedOrder(CLIModel):
    """Processed order ready for shipping (from order-postage page)."""
    name: str = Field(description="Customer name")
    order_id: str = Field(frozen=True, alias="orderId", description="Marketplace order ID")
    marketplace: Platform = Field(description="Marketplace platform")
    lots: int = Field(default=0, description="Number of lots")
    items: int = Field(default=0, description="Total item quantity")
    total: str = Field(default="0.00", description="Order total")
    email: str = Field(default="", description="Customer email")
    address: str = Field(default="", description="Full address (raw)")
    address1: str = Field(default="", description="Street address line 1")
    address2: str = Field(default="", description="Street address line 2")
    city: str = Field(default="", description="City")
    state: str = Field(default="", description="State/province")
    zip: str = Field(default="", description="ZIP/postal code")
    phone: str = Field(default="", description="Phone number")
    weight: str = Field(default="", description="Package weight")
    tracking_id: str = Field(default="", alias="trackingId", description="Tracking number")
    payment_method: str = Field(default="", alias="paymentMethod")
    shipping_method: str = Field(default="", alias="shippingMethod")

    class Config:
        populate_by_name = True


class ProcessedOrderList(CLIModel):
    """List of processed orders."""
    orders: List[ProcessedOrder]
    count: int = Field(default=0)

    def __init__(self, **data):
        if "count" not in data and "orders" in data:
            data["count"] = len(data["orders"])
        super().__init__(**data)


# ==================== Replacement Part Task Models ====================


class ReplacementPartTask(CLIModel):
    """Parsed replacement part task from standardized format.

    Format: [REPLACEMENT] | Platform: <platform> | Customer: <name> | Order: <orderId> | Part: <itemNo> <itemName> | Color: <color> | Qty: <qty> | Loc: <location>
    """
    index: int = Field(description="1-based task index")
    completed: bool = Field(default=False, description="Whether task is completed")
    platform: Platform = Field(description="Marketplace platform (bricklink or brickowl)")
    customer_name: str = Field(alias="customerName", description="Customer name")
    order_id: str = Field(alias="orderId", description="Marketplace order ID")
    item_no: str = Field(alias="itemNo", description="Part/item number")
    item_name: str = Field(alias="itemName", description="Part/item name")
    color: str = Field(description="Color name")
    qty: int = Field(description="Quantity")
    location: Optional[str] = Field(default=None, description="Bin location")
    raw_text: str = Field(alias="rawText", description="Original task text")

    class Config:
        populate_by_name = True

    @classmethod
    def from_task_text(cls, index: int, text: str, completed: bool = False) -> Optional["ReplacementPartTask"]:
        """Parse a task text into a ReplacementPartTask if it matches the format.

        Supports two formats:
        1. New format with Platform: [REPLACEMENT] | Platform: <platform> | Customer: <name> | Order: <orderId> | Part: <itemNo> <itemName> | Color: <color> | Qty: <qty> | Loc: <location>
        2. Legacy format without Platform: [REPLACEMENT] | Customer: <name> | Order: <orderId> | Part: <itemNo> <itemName> | Color: <color> | Qty: <qty> | Loc: <location>

        For legacy format, platform is inferred from order ID:
        - Order IDs starting with '30' and 8 digits = bricklink
        - Other order IDs = brickowl
        """
        import re

        # Try new format first (with Platform)
        pattern_new = r'^\[REPLACEMENT\] \| Platform: (bricklink|brickowl) \| Customer: (.+?) \| Order: (\d+) \| Part: (\S+) (.+?) \| Color: (.+?) \| Qty: (\d+)(?:\s*\|\s*Loc: (.+))?$'
        match = re.match(pattern_new, text)
        if match:
            return cls(
                index=index,
                completed=completed,
                platform=Platform(match.group(1)),
                customer_name=match.group(2),
                order_id=match.group(3),
                item_no=match.group(4),
                item_name=match.group(5),
                color=match.group(6),
                qty=int(match.group(7)),
                location=match.group(8) if match.group(8) else None,
                raw_text=text
            )

        # Try legacy format (without Platform)
        pattern_legacy = r'^\[REPLACEMENT\] \| Customer: (.+?) \| Order: (\d+) \| Part: (\S+) (.+?) \| Color: (.+?) \| Qty: (\d+)(?:\s*\|\s*Loc: (.+))?$'
        match = re.match(pattern_legacy, text)
        if match:
            order_id = match.group(2)
            # Infer platform from order ID format
            # Bricklink orders: 8 digits starting with 30
            # Brickowl orders: typically 7 digits
            if order_id.startswith('30') and len(order_id) == 8:
                platform = Platform.BRICKLINK
            else:
                platform = Platform.BRICKOWL

            return cls(
                index=index,
                completed=completed,
                platform=platform,
                customer_name=match.group(1),
                order_id=order_id,
                item_no=match.group(3),
                item_name=match.group(4),
                color=match.group(5),
                qty=int(match.group(6)),
                location=match.group(7) if match.group(7) else None,
                raw_text=text
            )

        return None

    @classmethod
    def format_task_text(
        cls,
        platform: str,
        customer_name: str,
        order_id: str,
        item_no: str,
        item_name: str,
        color: str,
        qty: int,
        location: Optional[str] = None
    ) -> str:
        """Format parameters into standardized task text."""
        parts = [
            "[REPLACEMENT]",
            f"Platform: {platform}",
            f"Customer: {customer_name}",
            f"Order: {order_id}",
            f"Part: {item_no} {item_name}",
            f"Color: {color}",
            f"Qty: {qty}"
        ]
        if location:
            parts.append(f"Loc: {location}")
        return " | ".join(parts)


class ReplacementPartTaskList(CLIModel):
    """List of replacement part tasks."""
    tasks: List[ReplacementPartTask]
    count: int = Field(default=0)

    def __init__(self, **data):
        if "count" not in data and "tasks" in data:
            data["count"] = len(data["tasks"])
        super().__init__(**data)


# ==================== Missing Parts Models (Legacy) ====================


class MissingPart(CLIModel):
    """Missing part parsed from a task.

    Formats:
    - New with color: "Bricklink Order #30823995 missing 2 x 44126pb022 Slope, Curved 6 x 2 (in Black) at location E-0971"
    - New without color: "Bricklink Order #30823995 missing 1 x 75270-1 Instruction Book at location F-INS"
    - Old (no item name): "Brickowl Order #9444944 missing 1 x 3008 (in Light Aqua) at location C-0961"
    - No name / no color: "Brickowl Order #5311768 missing 1 x 75270-1null at location F-INS"
      (Dashboard template concatenates item number with a JS ``null`` literal when the
      item name is missing; the trailing literal ``null`` is stripped from the item number.)
    """
    index: int = Field(description="1-based task index")
    platform: Platform
    order_id: str = Field(alias="orderId", description="Marketplace order ID")
    quantity: int = Field(description="Number of parts missing")
    item_number: str = Field(alias="itemNumber", description="LEGO part number")
    item_name: Optional[str] = Field(default=None, alias="itemName", description="Item name (None for old-format tasks)")
    color_name: str = Field(alias="colorName", description="Part color")
    location: str = Field(description="Inventory location")
    completed: bool = Field(default=False, description="Whether task is resolved")
    raw_text: str = Field(alias="rawText", description="Original task text")

    class Config:
        populate_by_name = True

    @classmethod
    def from_task_text(cls, index: int, text: str, completed: bool = False) -> Optional["MissingPart"]:
        """Parse a task text into a MissingPart if it matches the format.

        Tries four patterns in order:
        1. New format with color: includes item name and (in Color)
        2. New format without color: includes item name, no color
        3. Old format: no item name, has (in Color)
        4. No name / no color: bare item number (possibly with literal ``null`` suffix)
        """
        import re

        # 1. New format with color:
        # "Bricklink Order #30823995 missing 2 x 44126pb022 Slope, Curved 6 x 2 (in Black) at location E-0971"
        pattern_new_color = r'^(Bricklink|Brickowl) Order #(\d+) missing (\d+) x (\S+) ([^(].+?) \(in (.+)\)(?:\s+at location(?:\s+(\S+))?)?$'
        match = re.match(pattern_new_color, text, re.IGNORECASE)
        if match:
            return cls(
                index=index,
                platform=Platform(match.group(1).lower()),
                order_id=match.group(2),
                quantity=int(match.group(3)),
                item_number=match.group(4),
                item_name=match.group(5).strip(),
                color_name=match.group(6),
                location=match.group(7) or "",
                completed=completed,
                raw_text=text
            )

        # 2. New format without color:
        # "Bricklink Order #30823995 missing 1 x 75270-1 Instruction Book at location F-INS"
        pattern_new_no_color = r'^(Bricklink|Brickowl) Order #(\d+) missing (\d+) x (\S+) ([^(].+?) at location(?:\s+(\S+))?$'
        match = re.match(pattern_new_no_color, text, re.IGNORECASE)
        if match:
            return cls(
                index=index,
                platform=Platform(match.group(1).lower()),
                order_id=match.group(2),
                quantity=int(match.group(3)),
                item_number=match.group(4),
                item_name=match.group(5).strip(),
                color_name="",
                location=match.group(6) or "",
                completed=completed,
                raw_text=text
            )

        # 3. Old format (backward compat):
        # "Brickowl Order #9444944 missing 1 x 3008 (in Light Aqua) at location C-0961"
        pattern_old = r'^(Bricklink|Brickowl) Order #(\d+) missing (\d+) x (\S+) \(in (.+)\)(?:\s+at location(?:\s+(\S+))?)?$'
        match = re.match(pattern_old, text, re.IGNORECASE)
        if match:
            return cls(
                index=index,
                platform=Platform(match.group(1).lower()),
                order_id=match.group(2),
                quantity=int(match.group(3)),
                item_number=match.group(4),
                item_name=None,
                color_name=match.group(5),
                location=match.group(6) or "",
                completed=completed,
                raw_text=text
            )

        # 4. No name / no color (must be LAST so it does not shadow pattern_new_no_color):
        # "Brickowl Order #5311768 missing 1 x 75270-1null at location F-INS"
        # The BF dashboard template concatenates item_number with a literal JS ``null``
        # when the item name is unavailable; strip that exact trailing literal.
        pattern_no_name_no_color = r'^(Bricklink|Brickowl) Order #(\d+) missing (\d+) x (\S+) at location(?:\s+(\S+))?$'
        match = re.match(pattern_no_name_no_color, text, re.IGNORECASE)
        if match:
            item_number = match.group(4)
            if item_number.endswith("null"):
                item_number = item_number[:-4]
            return cls(
                index=index,
                platform=Platform(match.group(1).lower()),
                order_id=match.group(2),
                quantity=int(match.group(3)),
                item_number=item_number,
                item_name=None,
                color_name="",
                location=match.group(5) or "",
                completed=completed,
                raw_text=text
            )

        return None

    @classmethod
    def format_task_text(
        cls,
        platform: str,
        order_id: str,
        item_no: str,
        item_name: str,
        qty: int,
        location: str,
        color: Optional[str] = None
    ) -> str:
        """Format parameters into standardized missing-part task text.

        If color is "Not Applicable" (case-insensitive) or empty/None, the color
        portion is omitted entirely.
        """
        platform_display = "Bricklink" if platform.lower() == "bricklink" else "Brickowl"
        has_color = color and color.lower() != "not applicable"

        if has_color:
            return f"{platform_display} Order #{order_id} missing {qty} x {item_no} {item_name} (in {color}) at location {location}"
        else:
            return f"{platform_display} Order #{order_id} missing {qty} x {item_no} {item_name} at location {location}"


class MissingPartList(CLIModel):
    """List of missing parts."""
    parts: List[MissingPart]
    count: int = Field(default=0)

    def __init__(self, **data):
        if "count" not in data and "parts" in data:
            data["count"] = len(data["parts"])
        super().__init__(**data)


# ==================== Operation Result Models ====================


class ProcessResult(CLIModel):
    """Result of processing orders."""
    success: bool
    message: str
    processed: List[dict] = Field(default_factory=list)
    not_found: List[str] = Field(default_factory=list, alias="notFound")

    class Config:
        populate_by_name = True


class PostResult(CLIModel):
    """Result of posting orders."""
    success: bool
    message: str
    posted: List[dict] = Field(default_factory=list)
    missing_tracking: List[str] = Field(default_factory=list, alias="missingTracking")
    not_found: List[str] = Field(default_factory=list, alias="notFound")

    class Config:
        populate_by_name = True


class ResolveResult(CLIModel):
    """Result of resolving missing parts."""
    success: bool
    message: str
    resolved: List[dict] = Field(default_factory=list)


class TrackingResult(CLIModel):
    """Result of updating tracking number."""
    success: bool
    message: str
    order_id: str = Field(alias="orderId")
    tracking_number: str = Field(alias="trackingNumber")

    class Config:
        populate_by_name = True


# ==================== Factory Functions ====================


def create_task(data: dict) -> Task:
    """Create a Task model from scraped data."""
    return Task(**data)


def create_order(data: dict) -> Order:
    """Create an Order model from scraped data."""
    # Handle nested cost object
    if "cost" in data and isinstance(data["cost"], dict):
        data["cost"] = OrderCost(**data["cost"])
    return Order(**data)


def create_processed_order(data: dict) -> ProcessedOrder:
    """Create a ProcessedOrder model from scraped data."""
    return ProcessedOrder(**data)


def create_missing_part(data: dict) -> MissingPart:
    """Create a MissingPart model from scraped data."""
    return MissingPart(**data)
