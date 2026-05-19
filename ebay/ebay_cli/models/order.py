"""Order models for eBay CLI.

Models for eBay Fulfillment API order resources.
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import Field

from .base import EbayBaseModel


class OrderFulfillmentStatus(str, Enum):
    """Order fulfillment status values."""

    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    FULFILLED = "FULFILLED"


class PaymentStatus(str, Enum):
    """Payment status values."""

    PENDING = "PENDING"
    PAID = "PAID"
    FAILED = "FAILED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    FULLY_REFUNDED = "FULLY_REFUNDED"


class Amount(EbayBaseModel):
    """Monetary amount."""

    value: str = Field(..., description="Amount value")
    currency: str = Field("USD", description="Currency code")


class Address(EbayBaseModel):
    """Shipping or contact address."""

    address_line1: Optional[str] = Field(None, alias="addressLine1")
    address_line2: Optional[str] = Field(None, alias="addressLine2")
    city: Optional[str] = Field(None)
    state_or_province: Optional[str] = Field(None, alias="stateOrProvince")
    postal_code: Optional[str] = Field(None, alias="postalCode")
    country_code: Optional[str] = Field(None, alias="countryCode")


class Contact(EbayBaseModel):
    """Buyer contact information."""

    full_name: Optional[str] = Field(None, alias="fullName")
    primary_phone: Optional[dict] = Field(None, alias="primaryPhone")
    email: Optional[str] = Field(None)


class ShippingFulfillment(EbayBaseModel):
    """Shipping fulfillment details."""

    fulfillment_id: str = Field(..., alias="fulfillmentId", frozen=True)
    shipped_date: Optional[str] = Field(None, alias="shippedDate")
    shipping_carrier_code: Optional[str] = Field(None, alias="shippingCarrierCode")
    tracking_number: Optional[str] = Field(None, alias="trackingNumber")


class LineItem(EbayBaseModel):
    """Order line item."""

    line_item_id: str = Field(..., alias="lineItemId", frozen=True)
    title: str = Field(...)
    sku: Optional[str] = Field(None)
    quantity: int = Field(1, ge=1)
    line_item_cost: Optional[Amount] = Field(None, alias="lineItemCost")
    legacy_item_id: Optional[str] = Field(None, alias="legacyItemId")
    listing_marketplace_id: Optional[str] = Field(None, alias="listingMarketplaceId")


class OrderPayment(EbayBaseModel):
    """Order payment summary."""

    payment_status: Optional[PaymentStatus] = Field(None, alias="paymentStatus")
    total_due_seller: Optional[Amount] = Field(None, alias="totalDueSeller")


class PricingSummary(EbayBaseModel):
    """Order pricing summary."""

    price_subtotal: Optional[Amount] = Field(None, alias="priceSubtotal")
    delivery_cost: Optional[Amount] = Field(None, alias="deliveryCost")
    total: Optional[Amount] = Field(None)


class Order(EbayBaseModel):
    """eBay Order model."""

    order_id: str = Field(..., alias="orderId", frozen=True)
    creation_date: Optional[str] = Field(None, alias="creationDate", frozen=True)
    last_modified_date: Optional[str] = Field(None, alias="lastModifiedDate")

    # Status
    order_fulfillment_status: Optional[OrderFulfillmentStatus] = Field(
        None,
        alias="orderFulfillmentStatus",
    )
    order_payment_status: Optional[PaymentStatus] = Field(
        None,
        alias="orderPaymentStatus",
    )

    # Buyer info
    buyer: Optional[dict] = Field(None, description="Buyer information")
    fulfillment_start_instructions: Optional[list[dict]] = Field(
        None,
        alias="fulfillmentStartInstructions",
    )

    # Line items
    line_items: list[LineItem] = Field(default_factory=list, alias="lineItems")

    # Pricing
    pricing_summary: Optional[PricingSummary] = Field(None, alias="pricingSummary")
    payment_summary: Optional[OrderPayment] = Field(None, alias="paymentSummary")

    # Fulfillments
    fulfillment_hrefs: Optional[list[str]] = Field(None, alias="fulfillmentHrefs")


class OrderResponse(EbayBaseModel):
    """Response from get orders."""

    orders: list[Order] = Field(default_factory=list)
    total: int = Field(0)
    limit: int = Field(50)
    offset: int = Field(0)
    href: Optional[str] = Field(None)
    next: Optional[str] = Field(None)
    prev: Optional[str] = Field(None)
