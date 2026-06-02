"""Pickup models for FedEx CLI.

Model Design Principles:
- Required fields have no default value (Pydantic enforces presence)
- Optional fields use Optional[Type] = None
- Use enums for fields with fixed value sets
- Create specific model subclasses for different entity types
- Use factory functions for polymorphic model creation

Read-Only Field Patterns (Pydantic native):
- Field(frozen=True): Immutable after model creation (raises error on assignment)
- Field(exclude=True): Excluded from model_dump() output
- Field(init=False): Excluded from __init__ (requires default value)
- Combine patterns as needed: Field(frozen=True, exclude=True)
"""
from enum import Enum
from typing import List, Optional, Dict, Any

from pydantic import Field

from .base import CLIModel


# ==================== Enums ====================
# Define enums for fields with fixed value sets


class CarrierCode(str, Enum):
    """FedEx carrier codes."""

    EXPRESS = "FDXE"
    GROUND = "FDXG"


class PickupStatus(str, Enum):
    """Status of a scheduled pickup."""

    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CountryRelationship(str, Enum):
    """Domestic or international."""

    DOMESTIC = "DOMESTIC"
    INTERNATIONAL = "INTERNATIONAL"


class PickupType(str, Enum):
    """Pickup request type."""

    SAME_DAY = "SAME_DAY"
    FUTURE_DAY = "FUTURE_DAY"


# ==================== Models ====================


class PickupAddress(CLIModel):
    """Address for pickup location."""

    street_lines: List[str]
    city: str
    state_or_province_code: str
    postal_code: str
    country_code: str = "US"
    residential: bool = False


class AccessTime(CLIModel):
    """Access time duration."""

    hours: int
    minutes: int


class PickupAvailabilityOption(CLIModel):
    """Availability option for a pickup request."""

    carrier: CarrierCode
    available: bool
    pickup_date: str  # YYYY-MM-DD
    cut_off_time: str  # HH:MM:SS
    access_time: AccessTime
    default_ready_time: str  # HH:MM:SS
    default_latest_time_options: Optional[str] = None  # HH:MM:SS
    early_cut_off_time: Optional[str] = None  # HH:MM:SS
    early_access_time: Optional[AccessTime] = None
    early_pickup_location_id: Optional[str] = None
    ready_time_options: Optional[List[str]] = None
    latest_time_options: Optional[List[str]] = None
    residential_available: bool = False


class Pickup(CLIModel):
    """Scheduled pickup details."""

    # Read-only field: server-assigned
    pickup_confirmation_code: str = Field(frozen=True)

    # Required fields
    carrier: CarrierCode
    scheduled_date: str  # YYYY-MM-DD
    status: PickupStatus = PickupStatus.SCHEDULED

    # Optional fields
    location: Optional[str] = None  # For FedEx Express only
    account_number: Optional[str] = None
    alerts: Optional[List[Dict[str, Any]]] = None


class PickupRequest(CLIModel):
    """Request model for scheduling a pickup."""

    account_number: str
    pickup_address: PickupAddress
    carrier_code: CarrierCode
    package_count: int
    ready_time: str  # ISO 8601 or HH:MM:SS
    close_time: str  # HH:MM:SS

    # Optional fields
    total_weight: Optional[Dict[str, Any]] = None  # {units: "LB"|"KG", value: float}
    remarks: Optional[str] = None
    country_relationship: CountryRelationship = CountryRelationship.DOMESTIC
    pickup_type: PickupType = PickupType.SAME_DAY
    tracking_number: Optional[str] = None
    commodity_description: Optional[str] = None


class CancelPickupRequest(CLIModel):
    """Request model for canceling a pickup."""

    account_number: str
    pickup_confirmation_code: str
    scheduled_date: str  # YYYY-MM-DD
    carrier_code: CarrierCode
    location: Optional[str] = None  # For FedEx Express only
    remarks: Optional[str] = None


# ==================== Factory Functions ====================


def create_pickup(data: dict) -> Pickup:
    """Create a Pickup model from API response data.

    Args:
        data: Raw dict from API response (typically from 'output' key)

    Returns:
        Pickup model instance

    Raises:
        ValidationError: If required fields are missing
    """
    # Map API response fields to model fields
    mapping = {
        "pickupConfirmationCode": "pickup_confirmation_code",
        "scheduledDate": "scheduled_date",
        "carrierCode": "carrier",
    }

    mapped_data = {mapping.get(k, k): v for k, v in data.items()}
    return Pickup(**mapped_data)


def create_availability_options(data: List[dict]) -> List[PickupAvailabilityOption]:
    """Create PickupAvailabilityOption models from API response data.

    Args:
        data: List of raw dicts from API response

    Returns:
        List of PickupAvailabilityOption model instances
    """
    result = []
    for item in data:
        # Map API response fields to model fields
        mapping = {
            "pickupDate": "pickup_date",
            "cutOffTime": "cut_off_time",
            "accessTime": "access_time",
            "defaultReadyTime": "default_ready_time",
            "defaultLatestTimeOptions": "default_latest_time_options",
            "earlyCutOffTime": "early_cut_off_time",
            "earlyAccessTime": "early_access_time",
            "earlyPickupLocationId": "early_pickup_location_id",
            "readyTimeOptions": "ready_time_options",
            "latestTimeOptions": "latest_time_options",
            "residentialAvailable": "residential_available",
        }

        mapped_item = {mapping.get(k, k): v for k, v in item.items()}
        result.append(PickupAvailabilityOption(**mapped_item))

    return result
