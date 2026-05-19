"""USPS CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.

Model Architecture:
- CLIModel: Base class with CLI-friendly configuration
- TrackingInfo: Complete tracking information for a package
- TrackingEvent: Individual tracking event/scan
- Address: Origin or destination address
- TrackingError: Error response for invalid tracking numbers

Usage:
    from .models import TrackingInfo, create_tracking_info

    # Create from API response
    tracking = create_tracking_info(api_response)

    # Access typed fields
    print(tracking.status)
    print(tracking.events[0].description)

    # Serialize to JSON
    print_json(tracking)
"""
from .base import CLIModel
from .item import (
    # Models
    Address,
    TrackingEvent,
    TrackingInfo,
    TrackingError,
    # Enums
    TrackingStatusCategory,
    # Factory functions
    create_tracking_info,
)

__all__ = [
    # Base
    "CLIModel",
    # Models
    "Address",
    "TrackingEvent",
    "TrackingInfo",
    "TrackingError",
    # Enums
    "TrackingStatusCategory",
    # Factory functions
    "create_tracking_info",
]
