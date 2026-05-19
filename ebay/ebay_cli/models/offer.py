"""Offer models for eBay CLI.

Models for eBay Inventory API offer resources.
"""
from enum import Enum
from typing import Optional

from pydantic import Field

from .base import EbayBaseModel


class OfferStatus(str, Enum):
    """Offer status values."""

    PUBLISHED = "PUBLISHED"
    UNPUBLISHED = "UNPUBLISHED"


class OfferFormat(str, Enum):
    """Offer format values."""

    FIXED_PRICE = "FIXED_PRICE"
    AUCTION = "AUCTION"


class ListingDuration(str, Enum):
    """Auction listing duration values."""

    DAYS_1 = "DAYS_1"
    DAYS_3 = "DAYS_3"
    DAYS_5 = "DAYS_5"
    DAYS_7 = "DAYS_7"
    DAYS_10 = "DAYS_10"
    DAYS_21 = "DAYS_21"
    DAYS_30 = "DAYS_30"
    GTC = "GTC"


class Amount(EbayBaseModel):
    """Monetary amount with currency."""

    value: str = Field(..., description="Amount value")
    currency: str = Field("USD", pattern="^[A-Z]{3}$", description="Currency code")


class PricingSummary(EbayBaseModel):
    """Pricing information for an offer."""

    price: Optional[Amount] = Field(None, description="Buy It Now price")
    auction_start_price: Optional[Amount] = Field(
        None,
        alias="auctionStartPrice",
        description="Auction starting price",
    )
    auction_reserve_price: Optional[Amount] = Field(
        None,
        alias="auctionReservePrice",
        description="Auction reserve price",
    )
    minimum_advertised_price: Optional[Amount] = Field(
        None,
        alias="minimumAdvertisedPrice",
        description="Minimum advertised price",
    )


class ListingPolicies(EbayBaseModel):
    """Policy IDs for an offer."""

    fulfillment_policy_id: Optional[str] = Field(
        None,
        alias="fulfillmentPolicyId",
        description="Fulfillment policy ID",
    )
    payment_policy_id: Optional[str] = Field(
        None,
        alias="paymentPolicyId",
        description="Payment policy ID",
    )
    return_policy_id: Optional[str] = Field(
        None,
        alias="returnPolicyId",
        description="Return policy ID",
    )


class ListingInfo(EbayBaseModel):
    """Information about a published listing."""

    listing_id: str = Field(..., alias="listingId", description="eBay listing ID", frozen=True)
    listing_status: Optional[str] = Field(
        None,
        alias="listingStatus",
        description="Listing status",
    )


class Offer(EbayBaseModel):
    """eBay Offer model."""

    offer_id: str = Field(..., alias="offerId", description="Offer ID", frozen=True)
    sku: str = Field(..., min_length=1, max_length=50, description="Associated SKU")
    marketplace_id: str = Field("EBAY_US", alias="marketplaceId", description="Marketplace ID")
    format: OfferFormat = Field(OfferFormat.FIXED_PRICE, description="Listing format")
    status: OfferStatus = Field(OfferStatus.UNPUBLISHED, description="Offer status", frozen=True)

    # Pricing
    pricing_summary: Optional[PricingSummary] = Field(
        None,
        alias="pricingSummary",
        description="Pricing information",
    )
    available_quantity: Optional[int] = Field(
        None,
        alias="availableQuantity",
        ge=0,
        description="Available quantity",
    )

    # Classification
    category_id: Optional[str] = Field(None, alias="categoryId", description="eBay category ID")
    listing_description: Optional[str] = Field(
        None,
        alias="listingDescription",
        description="Listing description HTML",
    )

    # Policies
    listing_policies: Optional[ListingPolicies] = Field(
        None,
        alias="listingPolicies",
        description="Policy references",
    )

    # Location
    merchant_location_key: Optional[str] = Field(
        None,
        alias="merchantLocationKey",
        description="Merchant location key",
    )

    # Auction-specific
    listing_duration: Optional[ListingDuration] = Field(
        None,
        alias="listingDuration",
        description="Auction duration",
    )

    # Published listing info
    listing: Optional[ListingInfo] = Field(None, description="Published listing info")


class OfferResponse(EbayBaseModel):
    """Response from get offers."""

    offers: list[Offer] = Field(default_factory=list, description="List of offers")
    total: int = Field(0, description="Total count")
    limit: int = Field(25, description="Page size")
    offset: int = Field(0, description="Current offset")
    href: Optional[str] = Field(None, description="Current page URL")
    next: Optional[str] = Field(None, description="Next page URL")
    prev: Optional[str] = Field(None, description="Previous page URL")


class OfferCreateResponse(EbayBaseModel):
    """Response from creating an offer."""

    offer_id: str = Field(..., alias="offerId", description="Created offer ID")


class PublishOfferResponse(EbayBaseModel):
    """Response from publishing an offer."""

    listing_id: str = Field(..., alias="listingId", description="Created listing ID")
