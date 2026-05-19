"""Product models for ClickBank CLI."""
from decimal import Decimal
from typing import Optional

from .base import CLIModel


class ProductApprovalStatus(CLIModel):
    ticket_id: Optional[int] = None
    status: Optional[str] = None
    last_action_performed_by: Optional[str] = None


class ProductImage(CLIModel):
    id: Optional[int] = None
    title: Optional[str] = None
    type: Optional[str] = None
    approved: Optional[bool] = None
    path: Optional[str] = None


class ProductPages(CLIModel):
    desktop: Optional[str] = None
    mobile: Optional[str] = None


class ProductCommission(CLIModel):
    purchase: Optional[Decimal] = None
    rebill: Optional[Decimal] = None
    no_rebill_commission: Optional[bool] = None
    commission_tier_override: Optional[bool] = None


class Product(CLIModel):
    sku: Optional[str] = None
    id: Optional[int] = None
    status: Optional[str] = None
    digital: Optional[bool] = None
    physical: Optional[bool] = None
    digitalRecurring: Optional[bool] = None
    physicalRecurring: Optional[bool] = None
    site: Optional[str] = None
    created: Optional[str] = None
    updated: Optional[str] = None
    approval_status: Optional[ProductApprovalStatus] = None
    language: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    image: Optional[ProductImage] = None
    thank_you_pages: Optional[ProductPages] = None
    pitch_pages: Optional[ProductPages] = None
    commission: Optional[ProductCommission] = None
    pricings: Optional[list[dict]] = None
    contracts: Optional[list[dict]] = None
    categories: Optional[dict] = None
    disable_geo_currency: Optional[bool] = None
    allow_currency_change: Optional[bool] = None
    us_tax_exempt: Optional[bool] = None
    reduced_upsell_markup: Optional[bool] = None
    skip_confirmation_page: Optional[bool] = None
    admin_download_url: Optional[str] = None
    admin_mobile_download_url: Optional[str] = None
    no_commission: Optional[bool] = None
    sale_refund_days_limit: Optional[int] = None
    rebill_refund_days_limit: Optional[int] = None
    admin_restrict_flexible_refund: Optional[bool] = None
    commission_tier_override: Optional[bool] = None
    deliveryMethod: Optional[str] = None
    deliverySpeed: Optional[str] = None
    maxQuantity: Optional[int] = None
    isPartOfOrderBump: Optional[bool] = None
    isInitialOfOrderBump: Optional[bool] = None
    isProductOfOrderBump: Optional[bool] = None


class ProductCreateResult(CLIModel):
    sku: str


class ProductDeleteResult(CLIModel):
    sku: str
    site: str
    deleted: bool
