"""Template models for eBay CLI.

Models for local listing templates.
"""
from datetime import datetime
from typing import Optional

from pydantic import Field

from .base import EbayBaseModel
from .offer import Amount, ListingPolicies, OfferFormat, ListingDuration
from .policy import MarketplaceId


class TemplatePricingSummary(EbayBaseModel):
    """Pricing summary for a template."""

    price: Optional[Amount] = Field(None)
    auction_start_price: Optional[Amount] = Field(None, alias="auctionStartPrice")


class TemplateContent(EbayBaseModel):
    """Template content that can be applied to offers."""

    marketplace_id: MarketplaceId = Field(MarketplaceId.EBAY_US, alias="marketplaceId")
    format: OfferFormat = Field(OfferFormat.FIXED_PRICE)
    category_id: Optional[str] = Field(None, alias="categoryId")
    pricing_summary: Optional[TemplatePricingSummary] = Field(None, alias="pricingSummary")
    available_quantity: Optional[int] = Field(None, alias="availableQuantity", ge=0)
    listing_description: Optional[str] = Field(None, alias="listingDescription")
    listing_policies: Optional[ListingPolicies] = Field(None, alias="listingPolicies")
    merchant_location_key: Optional[str] = Field(None, alias="merchantLocationKey")
    listing_duration: Optional[ListingDuration] = Field(None, alias="listingDuration")


class Template(EbayBaseModel):
    """Listing template record."""

    name: str = Field(..., min_length=1, max_length=100, pattern="^[a-zA-Z0-9-_]+$")
    description: Optional[str] = Field(None, max_length=500)
    template: TemplateContent = Field(...)
    created_at: str = Field(..., alias="created_at")
    updated_at: str = Field(..., alias="updated_at")

    @classmethod
    def create(cls, name: str, template: TemplateContent, description: Optional[str] = None) -> "Template":
        """Create a new template with timestamps."""
        now = datetime.utcnow().isoformat()
        return cls(
            name=name,
            description=description,
            template=template,
            created_at=now,
            updated_at=now,
        )
