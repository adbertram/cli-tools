"""DigitalOcean droplet models."""
from enum import Enum
from typing import List, Optional

from pydantic import Field

from .base import CLIModel


class ItemStatus(str, Enum):
    """DigitalOcean droplet status values."""

    NEW = "new"
    ACTIVE = "active"
    OFF = "off"
    ARCHIVED = "archived"


class Item(CLIModel):
    """Droplet summary model."""

    id: str = Field(frozen=True)
    name: str
    status: ItemStatus
    region: Optional[str] = None
    ip_address: Optional[str] = None
    tags: List[str] = []
    memory: Optional[int] = None
    vcpus: Optional[int] = None
    disk: Optional[int] = None


class ItemDetail(CLIModel):
    """Detailed droplet model."""

    id: str = Field(frozen=True)
    name: str
    status: ItemStatus
    region: Optional[str] = None
    ip_address: Optional[str] = None
    tags: List[str] = []
    memory: Optional[int] = None
    vcpus: Optional[int] = None
    disk: Optional[int] = None
    created_at: Optional[str] = None
    size_slug: Optional[str] = None
    locked: Optional[bool] = None
    features: List[str] = []
    image: Optional[str] = None
    metadata: Optional[dict] = None


def create_item(data: dict) -> Item:
    """Create a droplet summary model from API data."""
    return Item(**data)


def create_item_detail(data: dict) -> ItemDetail:
    """Create a detailed droplet model from API data."""
    return ItemDetail(**data)
