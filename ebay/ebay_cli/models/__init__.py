"""eBay CLI Pydantic models.

This module provides type-safe models for all eBay API resources.
"""

# Base
from .base import EbayBaseModel

# Image
from .image import Image, ImageUploadResponse

# Listing (unified model)
from .listing import (
    Listing,
    ListingStatus,
    ListingFormat,
    ItemCondition,
    CONDITION_ID_TO_ENUM,
    CONDITION_ENUM_TO_ID,
    is_valid_sku,
    listing_from_offer,
    listing_from_trading_api,
    merge_listing_data,
    PSEUDO_DRAFT_PRICE,
)

# Inventory
from .inventory import (
    InventoryItem,
    InventoryItemResponse,
    Product,
    Availability,
    ShipToLocationAvailability,
)

# Offer
from .offer import (
    Offer,
    OfferResponse,
    OfferCreateResponse,
    PublishOfferResponse,
    OfferStatus,
    OfferFormat,
    ListingDuration,
    Amount,
    PricingSummary,
    ListingPolicies,
    ListingInfo,
)

# Order
from .order import (
    Order,
    OrderResponse,
    OrderFulfillmentStatus,
    PaymentStatus,
    LineItem,
    ShippingFulfillment,
    Address,
    Contact,
)

# Policy
from .policy import (
    FulfillmentPolicy,
    FulfillmentPolicyResponse,
    PaymentPolicy,
    PaymentPolicyResponse,
    ReturnPolicy,
    ReturnPolicyResponse,
    MarketplaceId,
    ShippingService,
    CategoryType,
)

# Location
from .location import (
    InventoryLocation,
    InventoryLocationResponse,
    LocationType,
    LocationStatus,
)

# Search
from .search_result import SearchResult

# Template
from .template import (
    Template,
    TemplateContent,
    TemplatePricingSummary,
)

__all__ = [
    # Base
    "EbayBaseModel",
    # Image
    "Image",
    "ImageUploadResponse",
    # Listing
    "Listing",
    "ListingStatus",
    "ListingFormat",
    "ItemCondition",
    "CONDITION_ID_TO_ENUM",
    "CONDITION_ENUM_TO_ID",
    "is_valid_sku",
    "listing_from_offer",
    "listing_from_trading_api",
    "merge_listing_data",
    "PSEUDO_DRAFT_PRICE",
    # Inventory
    "InventoryItem",
    "InventoryItemResponse",
    "Product",
    "Availability",
    "ShipToLocationAvailability",
    # Offer
    "Offer",
    "OfferResponse",
    "OfferCreateResponse",
    "PublishOfferResponse",
    "OfferStatus",
    "OfferFormat",
    "ListingDuration",
    "Amount",
    "PricingSummary",
    "ListingPolicies",
    "ListingInfo",
    # Order
    "Order",
    "OrderResponse",
    "OrderFulfillmentStatus",
    "PaymentStatus",
    "LineItem",
    "ShippingFulfillment",
    "Address",
    "Contact",
    # Policy
    "FulfillmentPolicy",
    "FulfillmentPolicyResponse",
    "PaymentPolicy",
    "PaymentPolicyResponse",
    "ReturnPolicy",
    "ReturnPolicyResponse",
    "MarketplaceId",
    "ShippingService",
    "CategoryType",
    # Location
    "InventoryLocation",
    "InventoryLocationResponse",
    "LocationType",
    "LocationStatus",
    # Search
    "SearchResult",
    # Template
    "Template",
    "TemplateContent",
    "TemplatePricingSummary",
]
