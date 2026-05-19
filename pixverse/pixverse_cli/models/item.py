"""PixVerse video job models."""
from typing import Optional

from pydantic import Field

from .base import CLIModel


class Item(CLIModel):
    """Submitted PixVerse video job."""

    id: str = Field(frozen=True)
    name: str
    operation: str
    status_code: Optional[int] = None
    model: Optional[str] = None
    duration: Optional[int] = None
    quality: Optional[str] = None
    metadata: Optional[dict] = None


class ItemDetail(CLIModel):
    """Detailed PixVerse video job state."""

    id: str = Field(frozen=True)
    name: str
    operation: str
    status_code: Optional[int] = None
    model: Optional[str] = None
    duration: Optional[int] = None
    quality: Optional[str] = None
    metadata: Optional[dict] = None


def create_item(data: dict) -> Item:
    """Create a PixVerse submission model from API data."""
    return Item(**data)


def create_item_detail(data: dict) -> ItemDetail:
    """Create a PixVerse status model from API data."""
    return ItemDetail(**data)
