"""DoorDash data models.

Models accept the raw DoorDash GraphQL response shape (camelCase) and are
constructed with ``Order(**row)`` — no per-field factory required.
"""
import re
from typing import Any, Dict, List, Optional

from pydantic import Field, model_validator

from .base import CLIModel


class Address(CLIModel):
    id: Optional[str] = None
    formattedAddress: Optional[str] = None


class Business(CLIModel):
    id: Optional[str] = None
    name: Optional[str] = None


class Store(CLIModel):
    id: Optional[str] = None
    name: Optional[str] = None
    phoneNumber: Optional[str] = None
    business: Optional[Business] = None


class Money(CLIModel):
    unitAmount: Optional[int] = None
    currency: Optional[str] = "USD"
    decimalPlaces: Optional[int] = 2
    displayString: Optional[str] = None


class PaymentCard(CLIModel):
    id: Optional[str] = None
    last4: Optional[str] = None
    type: Optional[str] = None


class Creator(CLIModel):
    id: Optional[str] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None


class OrderItemExtraOption(CLIModel):
    menuExtraOptionId: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[int] = None
    quantity: Optional[int] = None


class OrderItemExtra(CLIModel):
    menuItemExtraId: Optional[str] = None
    name: Optional[str] = None
    orderItemExtraOptions: List[OrderItemExtraOption] = Field(default_factory=list)


class OrderItem(CLIModel):
    id: Optional[str] = None
    name: Optional[str] = None
    quantity: int = 1
    specialInstructions: Optional[str] = None
    substitutionPreferences: Optional[str] = None
    originalItemPrice: Optional[int] = None
    orderItemExtras: List[OrderItemExtra] = Field(default_factory=list)


class OrderNested(CLIModel):
    """The `orders` array inside an Order response; each entry holds its own items."""

    id: Optional[str] = None
    items: List[OrderItem] = Field(default_factory=list)


class Order(CLIModel):
    """A DoorDash order, parsed directly from the getConsumerOrdersWithDetails GraphQL shape."""

    id: Optional[str] = None
    orderUuid: Optional[str] = None
    deliveryUuid: Optional[str] = None
    createdAt: Optional[str] = None
    submittedAt: Optional[str] = None
    fulfilledAt: Optional[str] = None
    cancelledAt: Optional[str] = None
    specialInstructions: Optional[str] = None
    isPickup: bool = False
    isGroup: bool = False
    isGift: bool = False
    isRetail: bool = False
    isMerchantShipping: bool = False
    isReorderable: bool = False
    containsAlcohol: bool = False
    fulfillmentType: Optional[str] = None
    shoppingProtocol: Optional[str] = None
    store: Optional[Store] = None
    deliveryAddress: Optional[Address] = None
    grandTotal: Optional[Money] = None
    paymentCard: Optional[PaymentCard] = None
    creator: Optional[Creator] = None
    orders: List[OrderNested] = Field(default_factory=list)

    @property
    def items(self) -> List[OrderItem]:
        """Flatten the nested orders[].items[] structure used by DoorDash's API."""
        return [item for sub in self.orders for item in sub.items]

    def cart_summary(self) -> Dict[str, Any]:
        """Project this order into the cart-summary dict surfaced by --dry-run reorders.
        The reorderOrder mutation copies these line items verbatim, so this is a
        faithful preview of what the new cart will contain."""
        items: List[Dict[str, Any]] = []
        items_total_cents = 0
        for it in self.items:
            item_cents = 0
            modifiers = []
            for extra in it.orderItemExtras:
                for opt in extra.orderItemExtraOptions:
                    price = opt.price or 0
                    item_cents += price * (opt.quantity or 1)
                    modifiers.append({"category": extra.name, "name": opt.name, "price_cents": price})
            line_total_cents = item_cents * it.quantity
            items_total_cents += line_total_cents
            items.append({
                "name": it.name,
                "quantity": it.quantity,
                "modifiers": modifiers,
                "line_total_cents": line_total_cents,
                "line_total_formatted": f"${line_total_cents / 100:.2f}" if line_total_cents else None,
            })
        return {
            "store_name": self.store.name if self.store else None,
            "store_id": self.store.id if self.store else None,
            "items": items,
            "items_total_cents": items_total_cents,
            "items_total_formatted": f"${items_total_cents / 100:.2f}" if items_total_cents else None,
            "original_order_total_formatted": self.grandTotal.displayString if self.grandTotal else None,
        }


_FEE_RE = re.compile(r"\$(\d+(?:\.\d{2})?)")

# Keys that only the raw GraphQL feed shape carries. When a dict has none of
# these, it's already in our normalised shape — pass through unchanged.
_RAW_FEED_KEYS = ("averageRating", "displayDeliveryFee", "deliveryTime", "distanceFromConsumer", "tags", "status")


class Restaurant(CLIModel):
    """Storefront entry from the getFeedV2 query. The GraphQL shape (delivery time
    as min/max struct, fee as display string) is normalised by a model_validator
    so callers just do `Restaurant(**row)`."""

    id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    headerImgUrl: Optional[str] = None
    rating: Optional[float] = None
    deliveryFeeCents: Optional[int] = None
    deliveryMinutes: Optional[int] = None
    distanceMiles: Optional[float] = None
    isOpen: bool = True
    cuisines: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, row: Any) -> Any:
        if not isinstance(row, dict):
            return row
        if not any(k in row for k in _RAW_FEED_KEYS):
            return row
        dt = row.get("deliveryTime") or {}
        minutes = None
        if dt.get("minTime") and dt.get("maxTime"):
            minutes = (dt["minTime"] + dt["maxTime"]) // 2
        elif dt.get("asapMinutesRange"):
            parts = dt["asapMinutesRange"].split("-")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                minutes = (int(parts[0]) + int(parts[1])) // 2
        match = _FEE_RE.search(row.get("displayDeliveryFee") or "")
        return {
            "id": str(row.get("id") or ""),
            "name": row.get("name"),
            "description": row.get("description"),
            "headerImgUrl": row.get("headerImgUrl"),
            "rating": row.get("averageRating"),
            "deliveryFeeCents": int(float(match.group(1)) * 100) if match else None,
            "deliveryMinutes": minutes,
            "distanceMiles": row.get("distanceFromConsumer"),
            "isOpen": (row.get("status") or {}).get("isOpen", True),
            "cuisines": [t["name"] for t in (row.get("tags") or []) if t.get("name")],
        }
