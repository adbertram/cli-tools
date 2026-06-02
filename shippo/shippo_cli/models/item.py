"""Shippo CLI models for addresses, parcels, shipments, rates, transactions, and tracking.

Models convert Shippo SDK dataclasses to Pydantic models for CLI-friendly output.
All CLI commands return Pydantic models for type safety and JSON serialization.
"""
from datetime import datetime
from enum import Enum
from typing import List, Optional, Any

from pydantic import Field

from .base import CLIModel


# ==================== Enums ====================


class DistanceUnit(str, Enum):
    """Distance/length units."""
    IN = "in"
    CM = "cm"
    FT = "ft"
    MM = "mm"
    M = "m"
    YD = "yd"


class MassUnit(str, Enum):
    """Weight/mass units."""
    LB = "lb"
    OZ = "oz"
    KG = "kg"
    G = "g"


class LabelFileType(str, Enum):
    """Label file format types."""
    PDF = "PDF"
    PDF_4X6 = "PDF_4x6"
    PNG = "PNG"
    ZPLII = "ZPLII"


class TransactionStatus(str, Enum):
    """Transaction/label status."""
    SUCCESS = "SUCCESS"
    QUEUED = "QUEUED"
    WAITING = "WAITING"
    ERROR = "ERROR"
    REFUNDED = "REFUNDED"
    REFUNDPENDING = "REFUNDPENDING"
    REFUNDREJECTED = "REFUNDREJECTED"


class ShipmentStatus(str, Enum):
    """Shipment status."""
    SUCCESS = "SUCCESS"
    QUEUED = "QUEUED"
    WAITING = "WAITING"
    ERROR = "ERROR"


class TrackingStatusEnum(str, Enum):
    """Tracking status categories."""
    UNKNOWN = "UNKNOWN"
    PRE_TRANSIT = "PRE_TRANSIT"
    TRANSIT = "TRANSIT"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"
    FAILURE = "FAILURE"


# ==================== Address Models ====================


class Address(CLIModel):
    """Address model for shipment origins and destinations."""

    object_id: Optional[str] = Field(default=None, frozen=True)
    name: Optional[str] = None
    company: Optional[str] = None
    street1: Optional[str] = None
    street2: Optional[str] = None
    street3: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    country: str = "US"
    phone: Optional[str] = None
    email: Optional[str] = None
    is_residential: Optional[bool] = None
    is_complete: Optional[bool] = None
    metadata: Optional[str] = None
    test: Optional[bool] = None
    object_created: Optional[str] = None
    object_updated: Optional[str] = None
    object_owner: Optional[str] = None
    validation_results: Optional[dict] = None


class AddressCreate(CLIModel):
    """Model for creating a new address."""

    name: str
    street1: str
    city: str
    state: str
    zip: str
    country: str = "US"
    company: Optional[str] = None
    street2: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    is_residential: bool = True
    metadata: Optional[str] = None


# ==================== Parcel Models ====================


class Parcel(CLIModel):
    """Parcel/package model with dimensions and weight."""

    object_id: Optional[str] = Field(default=None, frozen=True)
    length: str = "7"
    width: str = "4"
    height: str = "1"
    weight: str = "8"
    distance_unit: str = "in"
    mass_unit: str = "oz"
    template: Optional[str] = None
    metadata: Optional[str] = None
    object_created: Optional[str] = None
    object_updated: Optional[str] = None
    object_owner: Optional[str] = None
    object_state: Optional[str] = None
    test: Optional[bool] = None


class ParcelCreate(CLIModel):
    """Model for creating a parcel."""

    length: str = "7"
    width: str = "4"
    height: str = "1"
    weight: str = "8"
    distance_unit: str = "in"
    mass_unit: str = "oz"
    template: Optional[str] = None
    metadata: Optional[str] = None


# ==================== Service Level Model ====================


class ServiceLevel(CLIModel):
    """Service level info (carrier + service name)."""

    name: Optional[str] = None
    token: Optional[str] = None
    terms: Optional[str] = None
    extended_token: Optional[str] = None
    parent_servicelevel: Optional[dict] = None


# ==================== Rate Model ====================


class Rate(CLIModel):
    """Shipping rate model with pricing and delivery estimates."""

    object_id: str = Field(frozen=True)
    provider: str
    servicelevel: Optional[ServiceLevel] = None
    amount: str
    currency: str
    amount_local: Optional[str] = None
    currency_local: Optional[str] = None
    estimated_days: Optional[int] = None
    duration_terms: Optional[str] = None
    arrives_by: Optional[str] = None
    carrier_account: Optional[str] = None
    shipment: Optional[str] = None
    zone: Optional[str] = None
    messages: Optional[List[dict]] = None
    attributes: Optional[List[str]] = None
    included_insurance_price: Optional[str] = None
    test: Optional[bool] = None
    object_created: Optional[str] = None
    object_owner: Optional[str] = None


# ==================== Shipment Model ====================


class Shipment(CLIModel):
    """Shipment model containing addresses, parcels, and rates."""

    object_id: str = Field(frozen=True)
    status: str
    address_from: Optional[Address] = None
    address_to: Optional[Address] = None
    address_return: Optional[Address] = None
    parcels: List[Parcel] = []
    rates: List[Rate] = []
    messages: Optional[List[dict]] = None
    metadata: Optional[str] = None
    shipment_date: Optional[str] = None
    carrier_accounts: Optional[List[str]] = None
    extra: Optional[dict] = None
    customs_declaration: Optional[str] = None
    test: Optional[bool] = None
    object_created: Optional[str] = None
    object_updated: Optional[str] = None
    object_owner: Optional[str] = None


class ShipmentCreate(CLIModel):
    """Model for creating a shipment."""

    address_from: AddressCreate
    address_to: AddressCreate
    parcels: List[ParcelCreate]
    extra: Optional[dict] = None
    metadata: Optional[str] = None
    shipment_date: Optional[str] = None
    carrier_accounts: Optional[List[str]] = None
    customs_declaration: Optional[str] = None


# ==================== Transaction (Label) Model ====================


class TransactionRate(CLIModel):
    """Rate info embedded in transaction."""

    amount: Optional[str] = None
    currency: Optional[str] = None
    provider: Optional[str] = None
    servicelevel_name: Optional[str] = None
    servicelevel_token: Optional[str] = None


class Transaction(CLIModel):
    """Transaction model representing a purchased shipping label."""

    object_id: str = Field(frozen=True)
    status: str
    tracking_number: Optional[str] = None
    label_url: Optional[str] = None
    commercial_invoice_url: Optional[str] = None
    qr_code_url: Optional[str] = None
    tracking_url_provider: Optional[str] = None
    tracking_status: Optional[str] = None
    eta: Optional[str] = None
    rate: Optional[TransactionRate] = None
    parcel: Optional[str] = None
    label_file_type: Optional[str] = None
    messages: Optional[List[dict]] = None
    metadata: Optional[str] = None
    test: Optional[bool] = None
    object_created: Optional[str] = None
    object_updated: Optional[str] = None
    object_owner: Optional[str] = None
    object_state: Optional[str] = None
    created_by: Optional[dict] = None


# ==================== Tracking Models ====================


class TrackingEvent(CLIModel):
    """A single tracking event in the tracking history."""

    object_id: Optional[str] = None
    status: Optional[str] = None
    status_details: Optional[str] = None
    status_date: Optional[str] = None
    location: Optional[dict] = None


class TrackingInfo(CLIModel):
    """Tracking information for a shipment."""

    tracking_number: str
    carrier: str
    tracking_status: Optional[TrackingEvent] = None
    tracking_history: List[TrackingEvent] = []
    address_from: Optional[dict] = None
    address_to: Optional[dict] = None
    eta: Optional[str] = None
    original_eta: Optional[str] = None
    servicelevel: Optional[ServiceLevel] = None
    metadata: Optional[str] = None
    messages: Optional[List[str]] = None
    transaction: Optional[str] = None


# ==================== Refund Model ====================


class Refund(CLIModel):
    """Refund model for voided labels."""

    object_id: str = Field(frozen=True)
    status: str
    transaction: Optional[str] = None
    object_created: Optional[str] = None
    object_updated: Optional[str] = None
    object_owner: Optional[str] = None
    test: Optional[bool] = None


# ==================== Factory Functions ====================


def _convert_datetime(dt: Any) -> Optional[str]:
    """Convert datetime to ISO string if present."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)


def _convert_servicelevel(sl: Any) -> Optional[ServiceLevel]:
    """Convert SDK servicelevel to CLI ServiceLevel model."""
    if sl is None:
        return None
    try:
        if hasattr(sl, '__dataclass_fields__'):
            return ServiceLevel(
                name=getattr(sl, 'name', None),
                token=getattr(sl, 'token', None),
                terms=getattr(sl, 'terms', None),
                extended_token=getattr(sl, 'extended_token', None),
                parent_servicelevel=getattr(sl, 'parent_servicelevel', None),
            )
        elif isinstance(sl, dict):
            return ServiceLevel(**sl)
    except (ValueError, TypeError, KeyError, AttributeError):
        pass
    return None


def create_address(sdk_address: Any) -> Address:
    """Create Address model from SDK Address dataclass."""
    if isinstance(sdk_address, dict):
        return Address(**sdk_address)

    return Address(
        object_id=getattr(sdk_address, 'object_id', None),
        name=getattr(sdk_address, 'name', None),
        company=getattr(sdk_address, 'company', None),
        street1=getattr(sdk_address, 'street1', None),
        street2=getattr(sdk_address, 'street2', None),
        street3=getattr(sdk_address, 'street3', None),
        city=getattr(sdk_address, 'city', None),
        state=getattr(sdk_address, 'state', None),
        zip=getattr(sdk_address, 'zip', None),
        country=getattr(sdk_address, 'country', 'US'),
        phone=getattr(sdk_address, 'phone', None),
        email=getattr(sdk_address, 'email', None),
        is_residential=getattr(sdk_address, 'is_residential', None),
        is_complete=getattr(sdk_address, 'is_complete', None),
        metadata=getattr(sdk_address, 'metadata', None),
        test=getattr(sdk_address, 'test', None),
        object_created=_convert_datetime(getattr(sdk_address, 'object_created', None)),
        object_updated=_convert_datetime(getattr(sdk_address, 'object_updated', None)),
        object_owner=getattr(sdk_address, 'object_owner', None),
        validation_results=_extract_validation_results(sdk_address),
    )


def _extract_validation_results(sdk_address: Any) -> Optional[dict]:
    """Extract validation results from SDK address."""
    vr = getattr(sdk_address, 'validation_results', None)
    if vr is None:
        return None
    if isinstance(vr, dict):
        return vr
    # Convert dataclass to dict
    try:
        from dataclasses import asdict
        return asdict(vr)
    except (ValueError, TypeError, AttributeError):
        return None


def create_parcel(sdk_parcel: Any) -> Parcel:
    """Create Parcel model from SDK Parcel dataclass."""
    if isinstance(sdk_parcel, dict):
        return Parcel(**sdk_parcel)

    # Handle enum values
    distance_unit = getattr(sdk_parcel, 'distance_unit', 'in')
    if hasattr(distance_unit, 'value'):
        distance_unit = distance_unit.value

    mass_unit = getattr(sdk_parcel, 'mass_unit', 'oz')
    if hasattr(mass_unit, 'value'):
        mass_unit = mass_unit.value

    return Parcel(
        object_id=getattr(sdk_parcel, 'object_id', None),
        length=str(getattr(sdk_parcel, 'length', '7')),
        width=str(getattr(sdk_parcel, 'width', '4')),
        height=str(getattr(sdk_parcel, 'height', '1')),
        weight=str(getattr(sdk_parcel, 'weight', '8')),
        distance_unit=str(distance_unit),
        mass_unit=str(mass_unit),
        template=getattr(sdk_parcel, 'template', None),
        metadata=getattr(sdk_parcel, 'metadata', None),
        object_created=_convert_datetime(getattr(sdk_parcel, 'object_created', None)),
        object_updated=_convert_datetime(getattr(sdk_parcel, 'object_updated', None)),
        object_owner=getattr(sdk_parcel, 'object_owner', None),
        object_state=getattr(sdk_parcel, 'object_state', None),
        test=getattr(sdk_parcel, 'test', None),
    )


def create_rate(sdk_rate: Any) -> Rate:
    """Create Rate model from SDK Rate dataclass."""
    if isinstance(sdk_rate, dict):
        return Rate(**sdk_rate)

    # Extract attributes as list of strings
    attrs = getattr(sdk_rate, 'attributes', None)
    if attrs:
        attrs = [str(a.value) if hasattr(a, 'value') else str(a) for a in attrs]

    return Rate(
        object_id=getattr(sdk_rate, 'object_id', ''),
        provider=getattr(sdk_rate, 'provider', ''),
        servicelevel=_convert_servicelevel(getattr(sdk_rate, 'servicelevel', None)),
        amount=str(getattr(sdk_rate, 'amount', '')),
        currency=str(getattr(sdk_rate, 'currency', '')),
        amount_local=str(getattr(sdk_rate, 'amount_local', '')) if getattr(sdk_rate, 'amount_local', None) else None,
        currency_local=str(getattr(sdk_rate, 'currency_local', '')) if getattr(sdk_rate, 'currency_local', None) else None,
        estimated_days=getattr(sdk_rate, 'estimated_days', None),
        duration_terms=getattr(sdk_rate, 'duration_terms', None),
        arrives_by=getattr(sdk_rate, 'arrives_by', None),
        carrier_account=getattr(sdk_rate, 'carrier_account', None),
        shipment=getattr(sdk_rate, 'shipment', None),
        zone=getattr(sdk_rate, 'zone', None),
        messages=_convert_messages(getattr(sdk_rate, 'messages', None)),
        attributes=attrs,
        included_insurance_price=getattr(sdk_rate, 'included_insurance_price', None),
        test=getattr(sdk_rate, 'test', None),
        object_created=_convert_datetime(getattr(sdk_rate, 'object_created', None)),
        object_owner=getattr(sdk_rate, 'object_owner', None),
    )


def _convert_messages(messages: Any) -> Optional[List[dict]]:
    """Convert SDK messages to list of dicts."""
    if messages is None:
        return None
    result = []
    for msg in messages:
        if isinstance(msg, dict):
            result.append(msg)
        elif hasattr(msg, '__dataclass_fields__'):
            from dataclasses import asdict
            result.append(asdict(msg))
    return result if result else None


def _extract_customs_declaration_id(sdk_shipment: Any) -> Optional[str]:
    """Extract customs declaration ID from SDK shipment.

    The customs_declaration field can be:
    - A string object_id
    - A CustomsDeclaration object with an object_id attribute
    - None
    """
    cd = getattr(sdk_shipment, 'customs_declaration', None)
    if cd is None:
        return None
    if isinstance(cd, str):
        return cd
    # It's an object, extract the object_id
    return getattr(cd, 'object_id', None)


def create_shipment(sdk_shipment: Any) -> Shipment:
    """Create Shipment model from SDK Shipment dataclass."""
    if isinstance(sdk_shipment, dict):
        return Shipment(**sdk_shipment)

    # Handle status enum
    status = getattr(sdk_shipment, 'status', 'UNKNOWN')
    if hasattr(status, 'value'):
        status = status.value

    return Shipment(
        object_id=getattr(sdk_shipment, 'object_id', ''),
        status=str(status),
        address_from=create_address(getattr(sdk_shipment, 'address_from', None)) if getattr(sdk_shipment, 'address_from', None) else None,
        address_to=create_address(getattr(sdk_shipment, 'address_to', None)) if getattr(sdk_shipment, 'address_to', None) else None,
        address_return=create_address(getattr(sdk_shipment, 'address_return', None)) if getattr(sdk_shipment, 'address_return', None) else None,
        parcels=[create_parcel(p) for p in getattr(sdk_shipment, 'parcels', [])],
        rates=[create_rate(r) for r in getattr(sdk_shipment, 'rates', [])],
        messages=_convert_messages(getattr(sdk_shipment, 'messages', None)),
        metadata=getattr(sdk_shipment, 'metadata', None),
        shipment_date=getattr(sdk_shipment, 'shipment_date', None),
        carrier_accounts=getattr(sdk_shipment, 'carrier_accounts', None),
        extra=_extract_extra(sdk_shipment),
        customs_declaration=_extract_customs_declaration_id(sdk_shipment),
        test=getattr(sdk_shipment, 'test', None),
        object_created=_convert_datetime(getattr(sdk_shipment, 'object_created', None)),
        object_updated=_convert_datetime(getattr(sdk_shipment, 'object_updated', None)),
        object_owner=getattr(sdk_shipment, 'object_owner', None),
    )


def _extract_extra(obj: Any) -> Optional[dict]:
    """Extract extra field from SDK object."""
    extra = getattr(obj, 'extra', None)
    if extra is None:
        return None
    if isinstance(extra, dict):
        return extra
    try:
        from dataclasses import asdict
        return asdict(extra)
    except (ValueError, TypeError, AttributeError):
        return None


def create_transaction(sdk_transaction: Any) -> Transaction:
    """Create Transaction model from SDK Transaction dataclass."""
    if isinstance(sdk_transaction, dict):
        return Transaction(**sdk_transaction)

    # Handle status enum
    status = getattr(sdk_transaction, 'status', 'UNKNOWN')
    if hasattr(status, 'value'):
        status = status.value

    # Handle tracking status enum
    tracking_status = getattr(sdk_transaction, 'tracking_status', None)
    if tracking_status and hasattr(tracking_status, 'value'):
        tracking_status = tracking_status.value

    # Handle label file type enum
    label_file_type = getattr(sdk_transaction, 'label_file_type', None)
    if label_file_type and hasattr(label_file_type, 'value'):
        label_file_type = label_file_type.value

    # Extract rate info
    sdk_rate = getattr(sdk_transaction, 'rate', None)
    rate = None
    if sdk_rate:
        rate = TransactionRate(
            amount=str(getattr(sdk_rate, 'amount', '')) if getattr(sdk_rate, 'amount', None) else None,
            currency=str(getattr(sdk_rate, 'currency', '')) if getattr(sdk_rate, 'currency', None) else None,
            provider=getattr(sdk_rate, 'provider', None),
            servicelevel_name=getattr(getattr(sdk_rate, 'servicelevel', None), 'name', None) if getattr(sdk_rate, 'servicelevel', None) else None,
            servicelevel_token=getattr(getattr(sdk_rate, 'servicelevel', None), 'token', None) if getattr(sdk_rate, 'servicelevel', None) else None,
        )

    return Transaction(
        object_id=getattr(sdk_transaction, 'object_id', ''),
        status=str(status),
        tracking_number=getattr(sdk_transaction, 'tracking_number', None),
        label_url=getattr(sdk_transaction, 'label_url', None),
        commercial_invoice_url=getattr(sdk_transaction, 'commercial_invoice_url', None),
        qr_code_url=getattr(sdk_transaction, 'qr_code_url', None),
        tracking_url_provider=getattr(sdk_transaction, 'tracking_url_provider', None),
        tracking_status=str(tracking_status) if tracking_status else None,
        eta=getattr(sdk_transaction, 'eta', None),
        rate=rate,
        parcel=getattr(sdk_transaction, 'parcel', None),
        label_file_type=str(label_file_type) if label_file_type else None,
        messages=_convert_messages(getattr(sdk_transaction, 'messages', None)),
        metadata=getattr(sdk_transaction, 'metadata', None),
        test=getattr(sdk_transaction, 'test', None),
        object_created=_convert_datetime(getattr(sdk_transaction, 'object_created', None)),
        object_updated=_convert_datetime(getattr(sdk_transaction, 'object_updated', None)),
        object_owner=getattr(sdk_transaction, 'object_owner', None),
        object_state=getattr(sdk_transaction, 'object_state', None),
        created_by=_extract_created_by(sdk_transaction),
    )


def _extract_created_by(obj: Any) -> Optional[dict]:
    """Extract created_by field from SDK object."""
    cb = getattr(obj, 'created_by', None)
    if cb is None:
        return None
    if isinstance(cb, dict):
        return cb
    try:
        from dataclasses import asdict
        return asdict(cb)
    except (ValueError, TypeError, AttributeError):
        return None


def create_tracking_event(sdk_event: Any) -> TrackingEvent:
    """Create TrackingEvent model from SDK TrackingStatus dataclass."""
    if isinstance(sdk_event, dict):
        return TrackingEvent(**sdk_event)

    # Handle status enum
    status = getattr(sdk_event, 'status', None)
    if status and hasattr(status, 'value'):
        status = status.value

    # Extract location
    location = getattr(sdk_event, 'location', None)
    if location and hasattr(location, '__dataclass_fields__'):
        from dataclasses import asdict
        location = asdict(location)

    return TrackingEvent(
        object_id=getattr(sdk_event, 'object_id', None),
        status=str(status) if status else None,
        status_details=getattr(sdk_event, 'status_details', None),
        status_date=_convert_datetime(getattr(sdk_event, 'status_date', None)),
        location=location,
    )


def create_tracking_info(sdk_track: Any) -> TrackingInfo:
    """Create TrackingInfo model from SDK Track dataclass."""
    if isinstance(sdk_track, dict):
        return TrackingInfo(**sdk_track)

    # Extract tracking status
    tracking_status = getattr(sdk_track, 'tracking_status', None)
    if tracking_status:
        tracking_status = create_tracking_event(tracking_status)

    # Extract tracking history
    history = getattr(sdk_track, 'tracking_history', [])
    tracking_history = [create_tracking_event(e) for e in history] if history else []

    # Extract addresses
    addr_from = getattr(sdk_track, 'address_from', None)
    if addr_from and hasattr(addr_from, '__dataclass_fields__'):
        from dataclasses import asdict
        addr_from = asdict(addr_from)

    addr_to = getattr(sdk_track, 'address_to', None)
    if addr_to and hasattr(addr_to, '__dataclass_fields__'):
        from dataclasses import asdict
        addr_to = asdict(addr_to)

    return TrackingInfo(
        tracking_number=getattr(sdk_track, 'tracking_number', ''),
        carrier=getattr(sdk_track, 'carrier', ''),
        tracking_status=tracking_status,
        tracking_history=tracking_history,
        address_from=addr_from,
        address_to=addr_to,
        eta=_convert_datetime(getattr(sdk_track, 'eta', None)),
        original_eta=_convert_datetime(getattr(sdk_track, 'original_eta', None)),
        servicelevel=_convert_servicelevel(getattr(sdk_track, 'servicelevel', None)),
        metadata=getattr(sdk_track, 'metadata', None),
        messages=getattr(sdk_track, 'messages', None),
        transaction=getattr(sdk_track, 'transaction', None),
    )


def create_refund(sdk_refund: Any) -> Refund:
    """Create Refund model from SDK Refund dataclass."""
    if isinstance(sdk_refund, dict):
        return Refund(**sdk_refund)

    # Handle status enum
    status = getattr(sdk_refund, 'status', 'UNKNOWN')
    if hasattr(status, 'value'):
        status = status.value

    return Refund(
        object_id=getattr(sdk_refund, 'object_id', ''),
        status=str(status),
        transaction=getattr(sdk_refund, 'transaction', None),
        object_created=_convert_datetime(getattr(sdk_refund, 'object_created', None)),
        object_updated=_convert_datetime(getattr(sdk_refund, 'object_updated', None)),
        object_owner=getattr(sdk_refund, 'object_owner', None),
        test=getattr(sdk_refund, 'test', None),
    )


# ==================== Carrier Account Models ====================


class CarrierAccountServiceLevel(CLIModel):
    """Service level available for a carrier account."""

    name: Optional[str] = None
    token: Optional[str] = None
    supports_return_labels: Optional[bool] = None


class CarrierAccount(CLIModel):
    """Carrier account model representing a connected shipping carrier."""

    object_id: Optional[str] = Field(default=None, frozen=True)
    account_id: str
    carrier: str
    carrier_name: Optional[str] = None
    active: Optional[bool] = None
    is_shippo_account: Optional[bool] = None
    metadata: Optional[str] = None
    object_owner: Optional[str] = None
    service_levels: List[CarrierAccountServiceLevel] = []
    test: Optional[bool] = None


def create_carrier_account_service_level(sdk_sl: Any) -> CarrierAccountServiceLevel:
    """Create CarrierAccountServiceLevel model from SDK dataclass."""
    if isinstance(sdk_sl, dict):
        return CarrierAccountServiceLevel(**sdk_sl)

    return CarrierAccountServiceLevel(
        name=getattr(sdk_sl, 'name', None),
        token=getattr(sdk_sl, 'token', None),
        supports_return_labels=getattr(sdk_sl, 'supports_return_labels', None),
    )


def create_carrier_account(sdk_account: Any) -> CarrierAccount:
    """Create CarrierAccount model from SDK CarrierAccount dataclass."""
    if isinstance(sdk_account, dict):
        return CarrierAccount(**sdk_account)

    # Extract service levels
    service_levels = getattr(sdk_account, 'service_levels', [])
    if service_levels:
        service_levels = [create_carrier_account_service_level(sl) for sl in service_levels]
    else:
        service_levels = []

    # carrier_name might be an enum or Any type
    carrier_name = getattr(sdk_account, 'carrier_name', None)
    if carrier_name and hasattr(carrier_name, 'value'):
        carrier_name = carrier_name.value

    return CarrierAccount(
        object_id=getattr(sdk_account, 'object_id', None),
        account_id=getattr(sdk_account, 'account_id', ''),
        carrier=getattr(sdk_account, 'carrier', ''),
        carrier_name=str(carrier_name) if carrier_name else None,
        active=getattr(sdk_account, 'active', None),
        is_shippo_account=getattr(sdk_account, 'is_shippo_account', None),
        metadata=getattr(sdk_account, 'metadata', None),
        object_owner=getattr(sdk_account, 'object_owner', None),
        service_levels=service_levels,
        test=getattr(sdk_account, 'test', None),
    )
