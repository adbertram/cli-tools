"""Search result model for eBay marketplace search."""
from typing import Optional, Literal

from pydantic import Field

from .base import EbayBaseModel


class SearchResult(EbayBaseModel):
    """A single result from eBay completed/sold listings search."""

    item_id: str = Field(..., description="eBay item ID")
    title: str = Field(..., description="Listing title")
    price: str = Field(..., description="Sale/listing price")
    currency: str = Field("USD", description="Currency code")
    shipping_price: Optional[str] = Field(None, description="Shipping cost")
    status: Literal["sold", "unsold"] = Field(..., description="Whether item sold or went unsold")
    date_sold: Optional[str] = Field(None, description="Date the item sold")
    condition: Optional[str] = Field(None, description="Item condition")
    format: Optional[str] = Field(None, description="Listing format (Auction / Buy It Now)")
    bids: Optional[int] = Field(None, description="Number of bids (auction)")
    seller: Optional[str] = Field(None, description="Seller username")
    url: str = Field(..., description="Listing URL")
    image_url: Optional[str] = Field(None, description="Primary image URL")
