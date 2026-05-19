"""Policy models for eBay CLI.

Models for eBay Account API policy resources.
"""
from enum import Enum
from typing import Optional

from pydantic import Field

from .base import EbayBaseModel


class MarketplaceId(str, Enum):
    """eBay marketplace IDs."""

    EBAY_US = "EBAY_US"
    EBAY_CA = "EBAY_CA"
    EBAY_GB = "EBAY_GB"
    EBAY_AU = "EBAY_AU"
    EBAY_DE = "EBAY_DE"
    EBAY_FR = "EBAY_FR"
    EBAY_IT = "EBAY_IT"
    EBAY_ES = "EBAY_ES"


class CategoryType(EbayBaseModel):
    """Category type for policies."""

    name: str = Field(...)
    default: Optional[bool] = Field(None)


class Amount(EbayBaseModel):
    """Monetary amount."""

    value: str = Field(...)
    currency: str = Field("USD")


class ShippingOption(EbayBaseModel):
    """Shipping option within a service."""

    cost_type: Optional[str] = Field(None, alias="costType")
    shipping_cost: Optional[Amount] = Field(None, alias="shippingCost")
    additional_shipping_cost: Optional[Amount] = Field(None, alias="additionalShippingCost")


class ShippingService(EbayBaseModel):
    """Shipping service configuration."""

    shipping_carrier_code: Optional[str] = Field(None, alias="shippingCarrierCode")
    shipping_service_code: Optional[str] = Field(None, alias="shippingServiceCode")
    sort_order: Optional[int] = Field(None, alias="sortOrder")
    shipping_cost: Optional[Amount] = Field(None, alias="shippingCost")
    additional_shipping_cost: Optional[Amount] = Field(None, alias="additionalShippingCost")
    free_shipping: Optional[bool] = Field(None, alias="freeShipping")


class FulfillmentPolicy(EbayBaseModel):
    """Fulfillment (shipping) policy."""

    fulfillment_policy_id: str = Field(..., alias="fulfillmentPolicyId", frozen=True)
    name: str = Field(...)
    description: Optional[str] = Field(None)
    marketplace_id: MarketplaceId = Field(..., alias="marketplaceId")

    category_types: list[CategoryType] = Field(default_factory=list, alias="categoryTypes")
    handling_time: Optional[dict] = Field(None, alias="handlingTime")
    shipping_options: list[dict] = Field(default_factory=list, alias="shippingOptions")
    ship_to_locations: Optional[dict] = Field(None, alias="shipToLocations")
    global_shipping: Optional[bool] = Field(None, alias="globalShipping")
    pickup_drop_off: Optional[bool] = Field(None, alias="pickupDropOff")
    freight_shipping: Optional[bool] = Field(None, alias="freightShipping")


class FulfillmentPolicyResponse(EbayBaseModel):
    """Response from get fulfillment policies."""

    fulfillment_policies: list[FulfillmentPolicy] = Field(
        default_factory=list,
        alias="fulfillmentPolicies",
    )
    total: int = Field(0)


class PaymentMethod(EbayBaseModel):
    """Payment method configuration."""

    payment_method_type: str = Field(..., alias="paymentMethodType")
    brands: Optional[list[str]] = Field(None)


class PaymentPolicy(EbayBaseModel):
    """Payment policy."""

    payment_policy_id: str = Field(..., alias="paymentPolicyId", frozen=True)
    name: str = Field(...)
    description: Optional[str] = Field(None)
    marketplace_id: MarketplaceId = Field(..., alias="marketplaceId")

    category_types: list[CategoryType] = Field(default_factory=list, alias="categoryTypes")
    payment_methods: list[PaymentMethod] = Field(default_factory=list, alias="paymentMethods")
    immediate_pay: Optional[bool] = Field(None, alias="immediatePay")


class PaymentPolicyResponse(EbayBaseModel):
    """Response from get payment policies."""

    payment_policies: list[PaymentPolicy] = Field(
        default_factory=list,
        alias="paymentPolicies",
    )
    total: int = Field(0)


class ReturnPeriod(EbayBaseModel):
    """Return period configuration."""

    value: int = Field(...)
    unit: str = Field("DAY")


class ReturnPolicy(EbayBaseModel):
    """Return policy."""

    return_policy_id: str = Field(..., alias="returnPolicyId", frozen=True)
    name: str = Field(...)
    description: Optional[str] = Field(None)
    marketplace_id: MarketplaceId = Field(..., alias="marketplaceId")

    category_types: list[CategoryType] = Field(default_factory=list, alias="categoryTypes")
    returns_accepted: Optional[bool] = Field(None, alias="returnsAccepted")
    return_period: Optional[ReturnPeriod] = Field(None, alias="returnPeriod")
    refund_method: Optional[str] = Field(None, alias="refundMethod")
    return_shipping_cost_payer: Optional[str] = Field(None, alias="returnShippingCostPayer")
    restocking_fee_percentage: Optional[str] = Field(None, alias="restockingFeePercentage")


class ReturnPolicyResponse(EbayBaseModel):
    """Response from get return policies."""

    return_policies: list[ReturnPolicy] = Field(
        default_factory=list,
        alias="returnPolicies",
    )
    total: int = Field(0)
