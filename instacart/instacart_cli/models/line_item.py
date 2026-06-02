"""LineItem model for Instacart CLI."""
from typing import Optional

from pydantic import Field

from .amount import Amount
from .base import CLIModel
from .product import Product


class LineItem(CLIModel):
    """Line item in an order.

    Represents a product with quantity in a shopping cart or order.
    """

    line_item_id: str = Field(frozen=True, alias="lineItemId")
    product: Product
    quantity: int = Field(ge=1)
    subtotal: Optional[Amount] = None
    notes: Optional[str] = None
