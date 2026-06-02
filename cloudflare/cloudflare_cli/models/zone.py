"""Zone models for Cloudflare CLI.

Cloudflare zones represent domains (websites) managed by Cloudflare.
"""
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import Field

from .base import CLIModel


class ZoneStatus(str, Enum):
    """Status values for Cloudflare zones."""

    ACTIVE = "active"
    PENDING = "pending"
    INITIALIZING = "initializing"
    MOVED = "moved"
    DELETED = "deleted"
    DEACTIVATED = "deactivated"


class Zone(CLIModel):
    """Zone model returned by list commands.

    Represents a Cloudflare zone (domain).
    """

    # Read-only field: server-assigned
    id: str = Field(frozen=True)

    # Domain name
    name: str

    # Zone status
    status: ZoneStatus = ZoneStatus.ACTIVE

    # Whether zone is paused
    paused: bool = False

    # Zone type (full, partial, secondary)
    type: str = "full"

    # Cloudflare name servers
    name_servers: List[str] = []

    # Timestamps (read-only: server-assigned)
    created_on: Optional[datetime] = Field(default=None, frozen=True)
    modified_on: Optional[datetime] = Field(default=None, frozen=True)


class ZoneDetail(Zone):
    """Detailed zone model returned by get commands.

    Extends Zone with additional fields available when fetching a single zone.
    """

    # Plan information
    plan: Optional[dict] = None

    # Account that owns this zone
    account: Optional[dict] = None

    # Owner information
    owner: Optional[dict] = None

    # Original registrar
    original_registrar: Optional[str] = None

    # Original DNS host
    original_dnshost: Optional[str] = None

    # Original name servers
    original_name_servers: Optional[List[str]] = None


def create_zone(data: dict) -> Zone:
    """Create a Zone model from API response data.

    Args:
        data: Raw dict from API response

    Returns:
        Zone model instance

    Raises:
        ValidationError: If required fields are missing
    """
    return Zone(**data)


def create_zone_detail(data: dict) -> ZoneDetail:
    """Create a ZoneDetail model from API response data.

    Args:
        data: Raw dict from API response

    Returns:
        ZoneDetail model instance

    Raises:
        ValidationError: If required fields are missing
    """
    return ZoneDetail(**data)
