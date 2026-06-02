"""Instacart CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.

Model Architecture:
- CLIModel: Base class with CLI-friendly configuration
- Amount: Monetary values with currency
- Product: Grocery products
- LineItem: Products with quantity in orders
- Order/OrderDetail: Order information and details

Read-Only Fields:
- Use Field(frozen=True) for immutable fields (id, timestamps)
- Use Field(alias="camelCase") for API field name mapping

Usage:
    from .models import Order, OrderDetail, create_order

    # Create from API response
    order = create_order(api_response)

    # Access typed fields
    print(order.order_id)
    print(order.status)
    print(order.line_items[0].product.name)

    # Serialize to JSON
    print_json(order)
"""
from .amount import Amount
from .base import CLIModel
from .line_item import LineItem
from .order import (
    DeliveryAddress,
    Order,
    OrderCreate,
    OrderDetail,
    OrderStatus,
    create_order,
    create_order_detail,
)
from .product import Product

__all__ = [
    # Base
    "CLIModel",
    # Models
    "Amount",
    "Product",
    "LineItem",
    "Order",
    "OrderDetail",
    "OrderCreate",
    "DeliveryAddress",
    # Enums
    "OrderStatus",
    # Factory functions
    "create_order",
    "create_order_detail",
]
