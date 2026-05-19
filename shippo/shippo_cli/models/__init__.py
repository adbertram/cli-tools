"""Shippo CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.

Model Architecture:
- CLIModel: Base class with CLI-friendly configuration
- Address, Parcel, Shipment, Rate, Transaction, TrackingInfo: Core models
- Factory functions convert SDK dataclasses to Pydantic models

Usage:
    from .models import Address, Shipment, create_address, create_shipment

    # Create from SDK response
    address = create_address(sdk_address)
    shipment = create_shipment(sdk_shipment)

    # Serialize to JSON
    print_json(address)
"""
from .base import CLIModel
from .item import (
    # Enums
    DistanceUnit,
    MassUnit,
    LabelFileType,
    TransactionStatus,
    ShipmentStatus,
    TrackingStatusEnum,
    # Models
    Address,
    AddressCreate,
    Parcel,
    ParcelCreate,
    ServiceLevel,
    Rate,
    Shipment,
    ShipmentCreate,
    TransactionRate,
    Transaction,
    TrackingEvent,
    TrackingInfo,
    Refund,
    CarrierAccountServiceLevel,
    CarrierAccount,
    # Factory functions
    create_address,
    create_parcel,
    create_rate,
    create_shipment,
    create_transaction,
    create_tracking_event,
    create_tracking_info,
    create_refund,
    create_carrier_account_service_level,
    create_carrier_account,
)

__all__ = [
    # Base
    "CLIModel",
    # Enums
    "DistanceUnit",
    "MassUnit",
    "LabelFileType",
    "TransactionStatus",
    "ShipmentStatus",
    "TrackingStatusEnum",
    # Models
    "Address",
    "AddressCreate",
    "Parcel",
    "ParcelCreate",
    "ServiceLevel",
    "Rate",
    "Shipment",
    "ShipmentCreate",
    "TransactionRate",
    "Transaction",
    "TrackingEvent",
    "TrackingInfo",
    "Refund",
    "CarrierAccountServiceLevel",
    "CarrierAccount",
    # Factory functions
    "create_address",
    "create_parcel",
    "create_rate",
    "create_shipment",
    "create_transaction",
    "create_tracking_event",
    "create_tracking_info",
    "create_refund",
    "create_carrier_account_service_level",
    "create_carrier_account",
]
