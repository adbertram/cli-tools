"""Thunderbit extraction result models."""
from typing import Optional

from pydantic import Field

from .base import CLIModel


class Item(CLIModel):
    """Thunderbit distillation result."""

    id: str = Field(frozen=True)
    name: str
    output_kind: str
    metadata: Optional[dict] = None


class ItemDetail(CLIModel):
    """Thunderbit extraction result."""

    id: str = Field(frozen=True)
    name: str
    output_kind: str
    metadata: Optional[dict] = None


def create_item(data: dict) -> Item:
    """Create a Thunderbit distillation result model."""
    return Item(**data)


def create_item_detail(data: dict) -> ItemDetail:
    """Create a Thunderbit extraction result model."""
    return ItemDetail(**data)
