"""Order models for ClickBank CLI."""
from decimal import Decimal
from typing import Optional

from pydantic import Field

from .base import CLIModel


class OrderContactField(CLIModel):
    field: Optional[str] = None
    value: Optional[str] = None


class OrderVendorVariable(CLIModel):
    name: Optional[str] = None
    value: Optional[str] = None


class OrderVendorVariableArray(CLIModel):
    item: list[OrderVendorVariable] = Field(default_factory=list)


class OrderLineItem(CLIModel):
    itemNo: Optional[str] = None
    productTitle: Optional[str] = None
    recurring: Optional[bool] = None
    shippable: Optional[bool] = None
    customerAmount: Optional[Decimal] = None
    accountAmount: Optional[Decimal] = None
    quantity: Optional[int] = None
    lineItemType: Optional[str] = None
    refundsBlocked: Optional[bool] = None
    rebillAmount: Optional[Decimal] = None
    processedPayments: Optional[int] = None
    futurePayments: Optional[int] = None
    nextPaymentDate: Optional[str] = None
    status: Optional[str] = None
    role: Optional[str] = None


class OrderCommonTrackingParameters(CLIModel):
    clickTimestamp: Optional[str] = None
    clickId: Optional[str] = None
    useragent: Optional[str] = None
    deviceType: Optional[str] = None
    deviceBrand: Optional[str] = None
    deviceModel: Optional[str] = None
    os: Optional[str] = None
    osVersion: Optional[str] = None
    browser: Optional[str] = None
    browserVersion: Optional[str] = None
    browserLang: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    cbPage: Optional[str] = None
    trackingType: Optional[str] = None


class OrderAffiliateTrackingParameters(CLIModel):
    offer: Optional[str] = None
    trafficType: Optional[str] = None
    trafficSource: Optional[str] = None
    campaign: Optional[str] = None
    adgroup: Optional[str] = None
    ad: Optional[str] = None
    creative: Optional[str] = None
    extclid: Optional[str] = None
    fbclid: Optional[str] = None
    affSub1: Optional[str] = None
    affSub2: Optional[str] = None
    affSub3: Optional[str] = None
    affSub4: Optional[str] = None
    affSub5: Optional[str] = None
    uniqueAffSub1: Optional[str] = None
    uniqueAffSub2: Optional[str] = None
    uniqueAffSub3: Optional[str] = None
    uniqueAffSub4: Optional[str] = None
    uniqueAffSub5: Optional[str] = None
    contactId: Optional[str] = None


class Order(CLIModel):
    transactionTime: Optional[str] = None
    receipt: Optional[str] = None
    trackingId: Optional[str] = None
    paytmentMethod: Optional[str] = None
    transactionType: Optional[str] = None
    totalOrderAmount: Optional[Decimal] = None
    totalShippingAmount: Optional[Decimal] = None
    totalTaxAmount: Optional[Decimal] = None
    vendor: Optional[str] = None
    affiliate: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    lastName: Optional[str] = None
    firstName: Optional[str] = None
    currency: Optional[str] = None
    declinedConsent: Optional[bool] = None
    email: Optional[str] = None
    postalCode: Optional[str] = None
    customerContactInfo: list[OrderContactField] = Field(default_factory=list)
    role: Optional[str] = None
    fullName: Optional[str] = None
    customerRefundableState: Optional[str] = None
    vendorVariables: Optional[OrderVendorVariableArray] = None
    lineItemData: list[OrderLineItem] = Field(default_factory=list)
    commonTrackingParameters: Optional[OrderCommonTrackingParameters] = None
    affiliateTrackingParameters: Optional[OrderAffiliateTrackingParameters] = None


class OrderCount(CLIModel):
    count: int
