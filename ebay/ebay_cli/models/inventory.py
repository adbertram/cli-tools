"""Inventory models for eBay CLI.

Models for eBay Inventory API resources.
"""
from typing import Optional

from pydantic import Field

from .base import EbayBaseModel
from .listing import ItemCondition


class Product(EbayBaseModel):
    """Product details within an inventory item."""

    title: str = Field(..., max_length=80, description="Product title")
    description: Optional[str] = Field(None, description="Product description")
    image_urls: list[str] = Field(
        default_factory=list,
        alias="imageUrls",
        max_length=12,
        description="Product image URLs",
    )
    aspects: Optional[dict[str, list[str]]] = Field(None, description="Product aspects/attributes")
    brand: Optional[str] = Field(None, description="Brand name")
    mpn: Optional[str] = Field(None, description="Manufacturer part number")
    ean: Optional[list[str]] = Field(None, description="EAN codes")
    isbn: Optional[list[str]] = Field(None, description="ISBN codes")
    upc: Optional[list[str]] = Field(None, description="UPC codes")
    epid: Optional[str] = Field(None, description="eBay product ID")


class ShipToLocationAvailability(EbayBaseModel):
    """Quantity available for shipping."""

    quantity: int = Field(0, ge=0, description="Available quantity")


class Availability(EbayBaseModel):
    """Availability information for an inventory item."""

    ship_to_location_availability: ShipToLocationAvailability = Field(
        ...,
        alias="shipToLocationAvailability",
        description="Shipping availability",
    )


class InventoryItem(EbayBaseModel):
    """eBay Inventory Item model."""

    sku: str = Field(..., min_length=1, max_length=50, description="Seller-defined SKU", frozen=True)
    locale: Optional[str] = Field(None, description="Locale code", frozen=True)
    product: Optional[Product] = Field(None, description="Product details")
    condition: Optional[str] = Field(None, description="Item condition")
    condition_description: Optional[str] = Field(
        None,
        alias="conditionDescription",
        description="Seller's condition description",
    )
    availability: Optional[Availability] = Field(None, description="Availability info")
    package_weight_and_size: Optional[dict] = Field(
        None,
        alias="packageWeightAndSize",
        description="Package dimensions and weight",
    )


class InventoryItemResponse(EbayBaseModel):
    """Response from get inventory items."""

    inventory_items: list[InventoryItem] = Field(
        default_factory=list,
        alias="inventoryItems",
        description="List of inventory items",
    )
    total: int = Field(0, description="Total count")
    limit: int = Field(25, description="Page size")
    offset: int = Field(0, description="Current offset")
    href: Optional[str] = Field(None, description="Current page URL")
    next: Optional[str] = Field(None, description="Next page URL")
    prev: Optional[str] = Field(None, description="Previous page URL")
