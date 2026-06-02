"""Order models for Instacart CLI."""
from enum import Enum
from typing import List, Optional

from pydantic import Field

from .amount import Amount
from .base import CLIModel
from .line_item import LineItem


class OrderStatus(str, Enum):
    """Status values for orders (workflowState in GraphQL)."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    SHOPPING = "shopping"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    CANCELED = "canceled"  # Instacart's spelling
    CANCELLED = "cancelled"


class Order(CLIModel):
    """Instacart order.

    Base order model returned by list commands.
    """

    order_id: str = Field(frozen=True, alias="orderId")
    status: str
    line_items: List[LineItem] = Field(default_factory=list, alias="lineItems")
    total: Optional[Amount] = None
    created_at: Optional[str] = Field(default=None, frozen=True, alias="createdAt")
    updated_at: Optional[str] = Field(default=None, frozen=True, alias="updatedAt")
    delivered_at: Optional[str] = Field(default=None, frozen=True, alias="deliveredAt")
    store_name: Optional[str] = Field(default=None, alias="storeName")
    service_type: Optional[str] = Field(default=None, alias="serviceType")


class DeliveryAddress(CLIModel):
    """Delivery address for an order."""

    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = Field(default=None, alias="zipCode")
    country: str = "US"
    unit: Optional[str] = None


class OrderDetail(Order):
    """Extended order details.

    Returned by get commands with full order information.
    """

    delivery_address: Optional[DeliveryAddress] = Field(
        default=None, alias="deliveryAddress"
    )
    delivery_instructions: Optional[str] = Field(
        default=None, alias="deliveryInstructions"
    )
    scheduled_delivery: Optional[str] = Field(default=None, alias="scheduledDelivery")
    shopper_name: Optional[str] = Field(default=None, alias="shopperName")
    metadata: Optional[dict] = None


class OrderCreate(CLIModel):
    """Model for creating new orders.

    Use this for POST request payloads.
    """

    line_items: List[dict] = Field(alias="lineItems")
    delivery_address: Optional[dict] = Field(default=None, alias="deliveryAddress")
    delivery_instructions: Optional[str] = Field(
        default=None, alias="deliveryInstructions"
    )
    scheduled_delivery: Optional[str] = Field(default=None, alias="scheduledDelivery")


# ==================== Factory Functions ====================


def create_order(data: dict) -> Order:
    """Create an Order model from API response data.

    Args:
        data: Raw dict from API response

    Returns:
        Order model instance

    Raises:
        ValidationError: If required fields are missing
    """
    return Order.model_validate(data)


def create_order_detail(data: dict) -> OrderDetail:
    """Create an OrderDetail model from API response data.

    Args:
        data: Raw dict from API response

    Returns:
        OrderDetail model instance

    Raises:
        ValidationError: If required fields are missing
    """
    return OrderDetail.model_validate(data)
