"""Listing model for eBay CLI.

Provides unified Listing model that abstracts eBay's Inventory API, Offer API,
and Trading API into a single consistent interface.
"""
import re
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import Field, field_validator, model_validator

from .base import EbayBaseModel
from .image import Image

# Sentinel price for pseudo-draft listings (appear in eBay UI as editable published listings)
PSEUDO_DRAFT_PRICE = "99999.00"


class ListingStatus(str, Enum):
    """Listing status values."""

    ACTIVE = "active"
    DRAFT = "draft"
    UNSOLD = "unsold"
    SOLD = "sold"


class ListingFormat(str, Enum):
    """Listing format values."""

    FIXED_PRICE = "fixed_price"
    AUCTION = "auction"


class ItemCondition(str, Enum):
    """eBay item condition values.

    See: https://developer.ebay.com/api-docs/sell/inventory/types/slr:ConditionEnum
    """

    NEW = "NEW"
    LIKE_NEW = "LIKE_NEW"
    NEW_OTHER = "NEW_OTHER"
    NEW_WITH_DEFECTS = "NEW_WITH_DEFECTS"
    MANUFACTURER_REFURBISHED = "MANUFACTURER_REFURBISHED"
    CERTIFIED_REFURBISHED = "CERTIFIED_REFURBISHED"
    EXCELLENT_REFURBISHED = "EXCELLENT_REFURBISHED"
    VERY_GOOD_REFURBISHED = "VERY_GOOD_REFURBISHED"
    GOOD_REFURBISHED = "GOOD_REFURBISHED"
    SELLER_REFURBISHED = "SELLER_REFURBISHED"
    PRE_OWNED_EXCELLENT = "PRE_OWNED_EXCELLENT"
    USED_EXCELLENT = "USED_EXCELLENT"
    PRE_OWNED_FAIR = "PRE_OWNED_FAIR"
    USED_VERY_GOOD = "USED_VERY_GOOD"
    USED_GOOD = "USED_GOOD"
    USED_ACCEPTABLE = "USED_ACCEPTABLE"
    FOR_PARTS_OR_NOT_WORKING = "FOR_PARTS_OR_NOT_WORKING"


# Bidirectional mapping between eBay condition IDs and condition enum strings.
# Source: https://developer.ebay.com/api-docs/sell/static/metadata/condition-id-values.html
CONDITION_ID_TO_ENUM: dict[str, str] = {
    "1000": "NEW",
    "1500": "NEW_OTHER",
    "1750": "NEW_WITH_DEFECTS",
    "2000": "CERTIFIED_REFURBISHED",
    "2010": "EXCELLENT_REFURBISHED",
    "2020": "VERY_GOOD_REFURBISHED",
    "2030": "GOOD_REFURBISHED",
    "2500": "SELLER_REFURBISHED",
    "2750": "LIKE_NEW",
    "2990": "PRE_OWNED_EXCELLENT",
    "3000": "USED_EXCELLENT",
    "3010": "PRE_OWNED_FAIR",
    "4000": "USED_VERY_GOOD",
    "5000": "USED_GOOD",
    "6000": "USED_ACCEPTABLE",
    "7000": "FOR_PARTS_OR_NOT_WORKING",
}

CONDITION_ENUM_TO_ID: dict[str, str] = {v: k for k, v in CONDITION_ID_TO_ENUM.items()}
# MANUFACTURER_REFURBISHED is deprecated but maps to 2000 (same as CERTIFIED_REFURBISHED)
CONDITION_ENUM_TO_ID["MANUFACTURER_REFURBISHED"] = "2000"


# SKU validation pattern: alphanumeric, hyphens, underscores, max 50 chars (eBay API requirement)
SKU_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,50}$")


class Listing(EbayBaseModel):
    """
    Unified listing model combining data from eBay's multiple APIs.

    Abstracts:
    - Inventory API (inventory items)
    - Offer API (draft and published offers)
    - Trading API (active listings)
    """

    # Identifiers
    sku: str = Field(..., min_length=1, max_length=50, description="User-defined SKU (primary key)")
    offer_id: Optional[str] = Field(None, description="Inventory API offer ID")
    item_id: Optional[str] = Field(None, description="eBay listing ID (null for drafts)")

    # Core details
    title: str = Field("", max_length=80, description="Listing title")
    description: Optional[str] = Field(None, description="Listing description")
    price: str = Field("0.00", description="Listing price")
    currency: str = Field("USD", pattern="^[A-Z]{3}$", description="Currency code")
    quantity: int = Field(0, ge=0, description="Available quantity")
    quantity_sold: int = Field(0, ge=0, description="Quantity sold")

    # Status & format
    status: ListingStatus = Field(ListingStatus.DRAFT, description="Listing status")
    format: ListingFormat = Field(ListingFormat.FIXED_PRICE, description="Listing format")

    # Classification
    category_id: Optional[str] = Field(None, description="eBay category ID")
    condition: Optional[str] = Field(None, description="Item condition")

    # Media
    images: list[Image] = Field(default_factory=list, max_length=12, description="Listing images")

    # Policies
    fulfillment_policy_id: Optional[str] = Field(None, description="Fulfillment policy ID")
    payment_policy_id: Optional[str] = Field(None, description="Payment policy ID")
    return_policy_id: Optional[str] = Field(None, description="Return policy ID")

    # Location
    location_id: Optional[str] = Field(None, description="Merchant location key")

    # eBay URL (only for active listings)
    url: Optional[str] = Field(None, description="eBay listing URL")

    @field_validator("sku")
    @classmethod
    def validate_sku(cls, v: str) -> str:
        """Validate SKU format per eBay requirements."""
        if not v or not v.strip():
            raise ValueError("SKU cannot be empty")
        v = v.strip()
        if len(v) > 50:
            raise ValueError("SKU must not exceed 50 characters")
        if not SKU_PATTERN.match(v):
            raise ValueError(
                "SKU must contain only alphanumeric characters (no hyphens, underscores, or special characters)"
            )
        return v

    @field_validator("price")
    @classmethod
    def validate_price(cls, v: str) -> str:
        """Validate price is a valid decimal string."""
        try:
            price = Decimal(v)
            if price < 0:
                raise ValueError("Price cannot be negative")
            return str(price)
        except Exception:
            raise ValueError(f"Invalid price format: {v}")

    @property
    def is_draft(self) -> bool:
        """Check if listing is a draft (unpublished)."""
        return self.status == ListingStatus.DRAFT

    @property
    def is_active(self) -> bool:
        """Check if listing is active (published)."""
        return self.status == ListingStatus.ACTIVE

    @property
    def is_unsold(self) -> bool:
        """Check if listing is unsold (ended without sale)."""
        return self.status == ListingStatus.UNSOLD

    @property
    def is_sold(self) -> bool:
        """Check if listing is sold."""
        return self.status == ListingStatus.SOLD

    @property
    def is_pseudo_draft(self) -> bool:
        """Check if listing is a pseudo-draft (active but at sentinel price $99,999)."""
        return self.is_active and self.price == PSEUDO_DRAFT_PRICE

    def to_dict(self) -> dict:
        """Convert model to dictionary for JSON output.

        Always includes policy ID fields (even when None) so they are
        discoverable by ``--properties`` filtering.
        """
        d = super().to_dict()
        # Ensure policy fields are always present for consistent output
        for key in ("fulfillment_policy_id", "payment_policy_id", "return_policy_id"):
            if key not in d:
                d[key] = None
        return d


def is_valid_sku(sku: str) -> bool:
    """Check if a SKU is valid per eBay requirements."""
    if not sku or not sku.strip():
        return False
    sku = sku.strip()
    if len(sku) > 50:
        return False
    return bool(SKU_PATTERN.match(sku))


def listing_from_offer(offer: dict, inventory_item: Optional[dict] = None) -> Optional[Listing]:
    """
    Create a Listing from an Offer API response.

    Args:
        offer: Offer dict from get_offer() or get_offers()
        inventory_item: Optional inventory item dict for additional data

    Returns:
        Listing instance or None if SKU is invalid
    """
    sku = offer.get("sku", "")
    if not is_valid_sku(sku):
        return None

    # Extract pricing
    pricing = offer.get("pricingSummary", {})
    price_info = pricing.get("price", {}) or pricing.get("auctionStartPrice", {})

    # Extract policies
    policies = offer.get("listingPolicies", {})

    # Determine status
    offer_status = offer.get("status", "UNPUBLISHED")
    status = ListingStatus.ACTIVE if offer_status == "PUBLISHED" else ListingStatus.DRAFT

    # Determine format
    offer_format = offer.get("format", "FIXED_PRICE")
    format_val = ListingFormat.AUCTION if offer_format == "AUCTION" else ListingFormat.FIXED_PRICE

    # Get listing URL if published
    listing_info = offer.get("listing", {})
    item_id = listing_info.get("listingId")
    url = f"https://www.ebay.com/itm/{item_id}" if item_id else None

    # Extract data from inventory item if available
    title = ""
    description = None
    condition = None
    images: list[Image] = []

    if inventory_item:
        product = inventory_item.get("product", {})
        title = product.get("title", "")
        description = product.get("description")
        condition = inventory_item.get("condition")

        # Build images list
        image_urls = product.get("imageUrls", [])
        for i, img_url in enumerate(image_urls):
            images.append(Image(url=img_url, position=i))

    return Listing(
        sku=sku,
        offer_id=offer.get("offerId"),
        item_id=item_id,
        title=title,
        description=description,
        price=price_info.get("value", "0.00"),
        currency=price_info.get("currency", "USD"),
        quantity=offer.get("availableQuantity", 0) or 0,
        quantity_sold=0,  # Not available from Offer API
        status=status,
        format=format_val,
        category_id=offer.get("categoryId"),
        condition=condition,
        images=images,
        fulfillment_policy_id=policies.get("fulfillmentPolicyId"),
        payment_policy_id=policies.get("paymentPolicyId"),
        return_policy_id=policies.get("returnPolicyId"),
        location_id=offer.get("merchantLocationKey"),
        url=url,
    )


def listing_from_trading_api(item: dict) -> Optional[Listing]:
    """
    Create a Listing from a Trading API (GetSellerList) response item.

    These are always active listings. May not have an associated offer.

    Args:
        item: Item dict parsed from Trading API XML

    Returns:
        Listing instance or None if SKU is invalid
    """
    sku = item.get("sku", "")
    if not is_valid_sku(sku):
        return None

    # Build images list
    images: list[Image] = []
    image_urls = item.get("image_urls", [])
    for i, img_url in enumerate(image_urls):
        images.append(Image(url=img_url, position=i))

    # If no image_urls but has image_url, use that
    if not images and item.get("image_url"):
        images.append(Image(url=item["image_url"], position=0))

    # Determine format from listing_type
    listing_type = item.get("listing_type", "")
    format_val = ListingFormat.AUCTION if listing_type == "Chinese" else ListingFormat.FIXED_PRICE

    return Listing(
        sku=sku,
        offer_id=None,  # Trading API doesn't provide offer ID
        item_id=item.get("item_id"),
        title=item.get("title", ""),
        description=None,  # Not available from GetSellerList
        price=item.get("price", "0.00"),
        currency=item.get("currency", "USD"),
        quantity=int(item.get("quantity", 0) or 0),
        quantity_sold=int(item.get("quantity_sold", 0) or 0),
        status=ListingStatus.ACTIVE,  # Trading API only returns active listings
        format=format_val,
        category_id=None,  # Not available from GetSellerList
        condition=None,  # Not available from GetSellerList
        images=images,
        fulfillment_policy_id=None,
        payment_policy_id=None,
        return_policy_id=None,
        location_id=None,
        url=item.get("url"),
    )


def merge_listing_data(offer_listing: Listing, trading_listing: Listing) -> Listing:
    """
    Merge data from offer-based listing with Trading API listing.

    Trading API provides: quantity_sold, url, current quantity
    Offer API provides: offer_id, policies, category_id, condition

    Args:
        offer_listing: Listing from Offer API
        trading_listing: Listing from Trading API

    Returns:
        Merged Listing with best data from both sources
    """
    return Listing(
        sku=offer_listing.sku,
        offer_id=offer_listing.offer_id,
        item_id=trading_listing.item_id or offer_listing.item_id,
        title=offer_listing.title or trading_listing.title,
        description=offer_listing.description,
        price=trading_listing.price or offer_listing.price,  # Trading API has current price
        currency=trading_listing.currency or offer_listing.currency,
        quantity=trading_listing.quantity or offer_listing.quantity,
        quantity_sold=trading_listing.quantity_sold,  # Only from Trading API
        status=ListingStatus.ACTIVE,  # If we're merging, it's published
        format=offer_listing.format,
        category_id=offer_listing.category_id,
        condition=offer_listing.condition,
        images=offer_listing.images or trading_listing.images,
        fulfillment_policy_id=offer_listing.fulfillment_policy_id,
        payment_policy_id=offer_listing.payment_policy_id,
        return_policy_id=offer_listing.return_policy_id,
        location_id=offer_listing.location_id,
        url=trading_listing.url or offer_listing.url,
    )
