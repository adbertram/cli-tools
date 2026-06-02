"""USPS Tracking models.

Models for USPS Tracking API responses.
"""
from enum import Enum
from typing import List, Optional

from .base import CLIModel


# ==================== Enums ====================


class TrackingStatusCategory(str, Enum):
    """USPS tracking status categories."""

    PRE_SHIPMENT = "Pre-Shipment"
    ACCEPTED = "Accepted"
    IN_TRANSIT = "In Transit"
    OUT_FOR_DELIVERY = "Out for Delivery"
    DELIVERED = "Delivered"
    ALERT = "Alert"
    UNKNOWN = "Unknown"


# ==================== Models ====================


class Address(CLIModel):
    """Address information for origin or destination."""

    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    country: Optional[str] = None


class TrackingEvent(CLIModel):
    """Individual tracking event/scan."""

    date: str
    time: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    country: Optional[str] = None
    status: str
    description: Optional[str] = None


class TrackingInfo(CLIModel):
    """Complete tracking information for a package.

    This is the primary model returned by tracking commands.
    """

    # Required fields
    tracking_number: str
    status: str

    # Optional fields
    status_category: Optional[str] = None
    status_summary: Optional[str] = None
    mail_class: Optional[str] = None
    mail_type: Optional[str] = None
    origin: Optional[Address] = None
    destination: Optional[Address] = None
    mailing_date: Optional[str] = None
    expected_delivery: Optional[str] = None
    delivery_window: Optional[str] = None
    services: List[str] = []
    events: List[TrackingEvent] = []


class TrackingError(CLIModel):
    """Error response for invalid tracking number."""

    tracking_number: str
    error: str
    error_code: Optional[str] = None


# ==================== Factory Functions ====================


def create_tracking_info(data: dict) -> TrackingInfo:
    """Create TrackingInfo from raw API response.

    Args:
        data: Raw tracking data from USPS API

    Returns:
        TrackingInfo model instance
    """
    # Format tracking events
    # The API may return either eventTimestamp (ISO8601) or separate eventDate/eventTime fields
    # It may also use eventType or eventName for the event status
    events = []
    for event in data.get("trackingEvents", []):
        # Parse date/time from eventTimestamp if present, otherwise use separate fields
        event_date = ""
        event_time = None
        if event.get("eventTimestamp"):
            # eventTimestamp format: "2023-08-02T07:31:00Z"
            timestamp = event["eventTimestamp"]
            if "T" in timestamp:
                date_part, time_part = timestamp.split("T")
                event_date = date_part
                # Remove trailing Z if present and format time
                event_time = time_part.rstrip("Z")[:8]  # HH:MM:SS
        else:
            event_date = event.get("eventDate", "")
            event_time = event.get("eventTime")

        # Use eventType or eventName for status
        event_status = event.get("eventType") or event.get("eventName", "")

        # Use eventZIP or eventZIPCode for zip
        event_zip = event.get("eventZIP") or event.get("eventZIPCode")

        events.append(
            TrackingEvent(
                date=event_date,
                time=event_time,
                city=event.get("eventCity"),
                state=event.get("eventState"),
                zip=event_zip,
                country=event.get("eventCountry"),
                status=event_status,
                description=event.get("eventDescription") or event_status,
            )
        )

    # Format origin address
    # The API may use originZIP or originZIPCode
    origin = None
    if any(data.get(f"origin{k}") for k in ["City", "State", "ZIP", "ZIPCode", "Country"]):
        origin = Address(
            city=data.get("originCity"),
            state=data.get("originState"),
            zip=data.get("originZIP") or data.get("originZIPCode"),
            country=data.get("originCountry"),
        )

    # Format destination address
    # The API may use destinationZIP or destinationZIPCode
    destination = None
    if any(
        data.get(f"destination{k}") for k in ["City", "State", "ZIP", "ZIPCode", "Country"]
    ):
        destination = Address(
            city=data.get("destinationCity"),
            state=data.get("destinationState"),
            zip=data.get("destinationZIP") or data.get("destinationZIPCode"),
            country=data.get("destinationCountry"),
        )

    # Format delivery window
    delivery_window = None
    delivery_exp = data.get("deliveryDateExpectation", {})
    if delivery_exp.get("expectedDeliveryWindowStart") and delivery_exp.get(
        "expectedDeliveryWindowEnd"
    ):
        delivery_window = f"{delivery_exp['expectedDeliveryWindowStart']} - {delivery_exp['expectedDeliveryWindowEnd']}"

    return TrackingInfo(
        tracking_number=data.get("trackingNumber", ""),
        status=data.get("status", "Unknown"),
        status_category=data.get("statusCategory"),
        status_summary=data.get("statusSummary"),
        mail_class=data.get("mailClass"),
        mail_type=data.get("mailType"),
        origin=origin,
        destination=destination,
        mailing_date=data.get("mailingDate"),
        expected_delivery=delivery_exp.get("expectedDeliveryDate"),
        delivery_window=delivery_window,
        services=data.get("services", []),
        events=events,
    )
