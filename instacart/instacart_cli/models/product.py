"""Product model for Instacart CLI."""
from typing import Optional

from pydantic import Field

from .amount import Amount
from .base import CLIModel


class Product(CLIModel):
    """Product item in an order.

    Represents a grocery product that can be ordered.
    """

    product_id: str = Field(frozen=True, alias="productId")
    name: Optional[str] = None  # Not always available in list queries
    price: Optional[Amount] = None
    description: Optional[str] = None
    image_url: Optional[str] = Field(default=None, alias="imageUrl")
    upc: Optional[str] = None
