"""FedEx CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.

Model Architecture:
- CLIModel: Base class with CLI-friendly configuration
- Pickup: Scheduled pickup details
- PickupAddress: Address for pickup location
- PickupAvailabilityOption: Available pickup times
- PickupRequest: Request for scheduling a pickup
- CancelPickupRequest: Request for canceling a pickup

Read-Only Fields:
- Use Field(frozen=True) for immutable fields (id, timestamps)
- Use Field(exclude=True) to exclude from model_dump()
- Use Field(init=False) to exclude from __init__

Usage:
    from .models import Pickup, PickupRequest, create_pickup

    # Create from API response
    pickup = create_pickup(api_response)

    # Access typed fields
    print(pickup.pickup_confirmation_code)
    print(pickup.carrier.value)

    # Serialize to JSON
    print_json(pickup)
"""
from .base import CLIModel
from .item import (
    # Models
    Pickup,
    PickupAddress,
    PickupAvailabilityOption,
    PickupRequest,
    CancelPickupRequest,
    AccessTime,
    # Enums
    CarrierCode,
    PickupStatus,
    CountryRelationship,
    PickupType,
    # Factory functions
    create_pickup,
    create_availability_options,
)

__all__ = [
    # Base
    "CLIModel",
    # Models
    "Pickup",
    "PickupAddress",
    "PickupAvailabilityOption",
    "PickupRequest",
    "CancelPickupRequest",
    "AccessTime",
    # Enums
    "CarrierCode",
    "PickupStatus",
    "CountryRelationship",
    "PickupType",
    # Factory functions
    "create_pickup",
    "create_availability_options",
]
