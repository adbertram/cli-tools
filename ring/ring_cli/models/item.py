"""Ring CLI domain models.

Models map onto the four Ring device families exposed by ring-doorbell:
- doorbots (doorbells)
- stickup_cams (cameras, floodlights)
- chimes (in-home chimes)
- other (intercoms and similar)

Each device family lives at a different REST endpoint and exposes a
different attribute surface, so we use a single ``Device`` shape that
flattens the common fields and keeps family-specific fields optional.

Events come from /clients_api/doorbots/<id>/history and use a uniform shape
across families.
"""
from enum import Enum
from typing import List, Optional

from pydantic import Field

from .base import CLIModel


class DeviceFamily(str, Enum):
    """Ring device families. Values match ring-doorbell ``family`` attribute."""

    DOORBOTS = "doorbots"
    AUTHORIZED_DOORBOTS = "authorized_doorbots"
    STICKUP_CAMS = "stickup_cams"
    CHIMES = "chimes"
    OTHER = "other"


class EventKind(str, Enum):
    """Ring history event kinds. Matches the ``kind`` field in /history responses."""

    DING = "ding"
    MOTION = "motion"
    ON_DEMAND = "on_demand"
    ALARM = "alarm"


class Device(CLIModel):
    """A Ring device — doorbell, camera, chime, or intercom."""

    id: int = Field(frozen=True)
    name: str
    family: DeviceFamily = Field(frozen=True)
    model: Optional[str] = None
    kind: Optional[str] = None
    location_id: Optional[str] = None
    timezone: Optional[str] = None
    address: Optional[str] = None

    # Health / connectivity (populated when update_health_data has been called)
    battery_life: Optional[int] = None
    wifi_name: Optional[str] = None
    wifi_signal_strength: Optional[int] = None
    connection_status: Optional[str] = None
    firmware: Optional[str] = None

    # Capability flags (family-specific; None when the capability does not apply)
    motion_detection: Optional[bool] = None
    lights: Optional[str] = None  # "on" / "off" for stickup_cams with lights
    siren: Optional[int] = None  # remaining-seconds counter
    volume: Optional[int] = None
    subscribed: Optional[bool] = None
    subscribed_motion: Optional[bool] = None
    has_subscription: Optional[bool] = None


class DeviceHealth(CLIModel):
    """Health snapshot for a single device — battery, wifi, connection."""

    id: int = Field(frozen=True)
    name: str
    family: DeviceFamily = Field(frozen=True)
    battery_life: Optional[int] = None
    wifi_name: Optional[str] = None
    wifi_signal_strength: Optional[int] = None
    connection_status: Optional[str] = None
    firmware: Optional[str] = None


class Event(CLIModel):
    """A single Ring event (ding, motion, on-demand, alarm)."""

    id: str = Field(frozen=True)
    device_id: int = Field(frozen=True)
    device_name: str
    kind: EventKind
    created_at: str
    answered: Optional[bool] = None
    recording_is_ready: Optional[bool] = None
    duration: Optional[int] = None
    cv_properties: Optional[dict] = None


class DownloadResult(CLIModel):
    """Result of downloading a recording for an event."""

    event_id: str = Field(frozen=True)
    device_id: int
    device_name: str
    kind: EventKind
    created_at: str
    path: str  # Absolute path to the downloaded MP4
    size_bytes: int


class SnapshotResult(CLIModel):
    """Result of capturing a fresh snapshot from a device."""

    device_id: int = Field(frozen=True)
    device_name: str
    family: DeviceFamily
    path: str  # Absolute path to the saved JPEG
    size_bytes: int


class MotionState(CLIModel):
    """Current motion-detection state for a device."""

    device_id: int = Field(frozen=True)
    device_name: str
    enabled: bool


class LightsState(CLIModel):
    """Current floodlight/lights state for a stickup_cam."""

    device_id: int = Field(frozen=True)
    device_name: str
    state: str  # "on" / "off"


class SirenState(CLIModel):
    """Current siren state for a stickup_cam."""

    device_id: int = Field(frozen=True)
    device_name: str
    remaining_seconds: int


class VolumeState(CLIModel):
    """Current volume setting for a device."""

    device_id: int = Field(frozen=True)
    device_name: str
    volume: int


def create_device(family: DeviceFamily, raw: dict) -> Device:
    """Build a Device from the ring-doorbell device wrapper's raw payload.

    ``raw`` is the underlying ring-doorbell ``device._attrs`` dict, which is
    the same shape returned by Ring's /clients_api endpoints.
    """
    return Device(
        id=int(raw["id"]),
        name=raw.get("description") or raw.get("name") or f"device-{raw['id']}",
        family=family,
        kind=raw.get("kind"),
        location_id=raw.get("location_id"),
        timezone=raw.get("time_zone") or raw.get("timezone"),
        address=raw.get("address"),
    )
