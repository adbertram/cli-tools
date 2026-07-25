"""Search result model for eBay marketplace search."""
from typing import Optional, Literal

from pydantic import Field

from .base import EbayBaseModel


class SearchResult(EbayBaseModel):
    """A single result from an eBay listings search (active or completed)."""

    item_id: str = Field(..., description="eBay item ID")
    title: str = Field(..., description="Listing title")
    price: str = Field(..., description="Current/listing price (current bid for active auctions)")
    currency: str = Field("USD", description="Currency code")
    shipping_price: Optional[str] = Field(None, description="Shipping cost")
    status: Literal["sold", "unsold", "active"] = Field(
        ..., description="'active' for live listings; 'sold'/'unsold' for completed comps"
    )
    date_sold: Optional[str] = Field(None, description="Date the item sold/ended (completed comps)")
    time_left: Optional[str] = Field(
        None, description="Time left as shown by eBay (active listings, e.g. '6d 4h', '1m (Today 3:52PM)')"
    )
    condition: Optional[str] = Field(None, description="Item condition")
    format: Optional[str] = Field(None, description="Listing format (Auction / Buy It Now / Best Offer)")
    bids: Optional[int] = Field(None, description="Number of bids (auction)")
    seller: Optional[str] = Field(None, description="Seller username")
    url: str = Field(..., description="Listing URL")
    image_url: Optional[str] = Field(None, description="Primary image URL")
