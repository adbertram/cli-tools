"""Item-detail model for an active eBay listing (browser-scraped /itm/<id>)."""
from typing import Optional

from pydantic import Field

from .base import EbayBaseModel


class ItemDetail(EbayBaseModel):
    """Detail view of a single eBay listing scraped from its /itm/<id> page.

    Populated primarily from the page's schema.org ``Product`` JSON-LD
    (price, currency, condition, availability, shipping) and supplemented
    with DOM values that JSON-LD does not carry (current bid count,
    time-left, quantity available, seller, and the fulfillment label rows
    behind ``local_pickup``/``ships``/``item_location``).
    """

    item_id: str = Field(..., description="eBay item ID")
    title: str = Field(..., description="Listing title")
    price: Optional[str] = Field(None, description="Current price (current bid for an auction)")
    currency: str = Field("USD", description="Currency code")
    format: Optional[str] = Field(None, description="Listing format (Auction / Buy It Now / Best Offer)")
    bin_price: Optional[str] = Field(None, description="Buy It Now price when present")
    current_bid: Optional[str] = Field(None, description="Current bid amount (auctions)")
    bids: Optional[int] = Field(None, description="Number of bids (auctions)")
    time_left: Optional[str] = Field(None, description="Time left as shown by eBay")
    shipping_price: Optional[str] = Field(None, description="Shipping cost to the default destination")
    local_pickup: bool = Field(
        False,
        description="True when eBay renders a local-pickup row (buyer can collect in person)",
    )
    ships: bool = Field(
        False,
        description="True when eBay's shipping row quotes a rate or a delivery estimate",
    )
    item_location: Optional[str] = Field(
        None,
        description="Item origin from the shipping row's 'Located in:' line (absent on pickup-only listings)",
    )
    condition: Optional[str] = Field(None, description="Item condition")
    availability: Optional[str] = Field(None, description="Availability (e.g. InStock, SoldOut)")
    ended: bool = Field(False, description="True when the listing has ended / is unavailable")
    quantity: Optional[str] = Field(None, description="Quantity available text (e.g. '5 available')")
    seller: Optional[str] = Field(None, description="Seller username or store name")
    brand: Optional[str] = Field(None, description="Brand (from JSON-LD)")
    url: str = Field(..., description="Canonical listing URL")
    image_url: Optional[str] = Field(None, description="Primary image URL")
