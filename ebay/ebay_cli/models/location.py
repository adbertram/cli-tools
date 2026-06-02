"""Location models for eBay CLI.

Models for eBay Inventory API location resources.
"""
from enum import Enum
from typing import Optional

from pydantic import Field

from .base import EbayBaseModel


class LocationType(str, Enum):
    """Merchant location type values."""

    WAREHOUSE = "WAREHOUSE"
    STORE = "STORE"


class LocationStatus(str, Enum):
    """Merchant location status values."""

    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class Address(EbayBaseModel):
    """Location address."""

    address_line1: str = Field(..., alias="addressLine1")
    address_line2: Optional[str] = Field(None, alias="addressLine2")
    city: str = Field(...)
    state_or_province: str = Field(..., alias="stateOrProvince")
    postal_code: str = Field(..., alias="postalCode")
    country: str = Field("US")


class GeoCoordinates(EbayBaseModel):
    """Geographic coordinates."""

    latitude: float = Field(...)
    longitude: float = Field(...)


class LocationDetails(EbayBaseModel):
    """Location details container."""

    address: Address = Field(...)
    geo_coordinates: Optional[GeoCoordinates] = Field(None, alias="geoCoordinates")


class OperatingHours(EbayBaseModel):
    """Operating hours for a location."""

    day_of_week_enum: str = Field(..., alias="dayOfWeekEnum")
    intervals: list[dict] = Field(default_factory=list)


class InventoryLocation(EbayBaseModel):
    """Merchant inventory location."""

    merchant_location_key: str = Field(
        ...,
        alias="merchantLocationKey",
        min_length=1,
        max_length=36,
        frozen=True,
    )
    name: str = Field(..., max_length=1000)
    location: LocationDetails = Field(...)
    location_types: list[LocationType] = Field(
        default_factory=list,
        alias="locationTypes",
    )
    merchant_location_status: LocationStatus = Field(
        LocationStatus.ENABLED,
        alias="merchantLocationStatus",
    )

    # Optional fields
    location_additional_information: Optional[str] = Field(
        None,
        alias="locationAdditionalInformation",
        max_length=256,
    )
    location_instructions: Optional[str] = Field(
        None,
        alias="locationInstructions",
        max_length=256,
    )
    location_web_url: Optional[str] = Field(None, alias="locationWebUrl")
    phone: Optional[str] = Field(None)
    operating_hours: Optional[list[OperatingHours]] = Field(None, alias="operatingHours")
    special_hours: Optional[list[dict]] = Field(None, alias="specialHours")


class InventoryLocationResponse(EbayBaseModel):
    """Response from get inventory locations."""

    locations: list[InventoryLocation] = Field(default_factory=list)
    total: int = Field(0)
    limit: int = Field(25)
    offset: int = Field(0)
    href: Optional[str] = Field(None)
    next: Optional[str] = Field(None)
    prev: Optional[str] = Field(None)
