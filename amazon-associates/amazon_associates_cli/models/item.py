"""Item models for AmazonAssociates CLI.

This file provides example models. Replace or extend with your own models.

Model Design Principles:
- Required fields have no default value (Pydantic enforces presence)
- Optional fields use Optional[Type] = None
- Use enums for fields with fixed value sets
- Create specific model subclasses for different entity types
- Use factory functions for polymorphic model creation

Read-Only Field Patterns (Pydantic native):
- Field(frozen=True): Immutable after model creation (raises error on assignment)
- Field(exclude=True): Excluded from model_dump() output
- Field(init=False): Excluded from __init__ (requires default value)
- Combine patterns as needed: Field(frozen=True, exclude=True)
"""
from enum import Enum
from typing import List, Optional

from pydantic import Field

from .base import CLIModel


# ==================== Enums ====================
# Define enums for fields with fixed value sets


class ItemStatus(str, Enum):
    """Status values for items."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"
    ARCHIVED = "archived"


class ItemType(str, Enum):
    """Type categories for items."""

    STANDARD = "standard"
    PREMIUM = "premium"
    CUSTOM = "custom"


# ==================== Models ====================


class Item(CLIModel):
    """Base item model returned by list commands.

    Required fields:
    - id: Unique identifier (always required)
    - name: Display name (always required)

    Optional fields have defaults and can be omitted.
    """

    # Read-only field: server-assigned, immutable
    id: str = Field(frozen=True)

    # Regular required field
    name: str

    # Optional fields with defaults
    status: ItemStatus = ItemStatus.ACTIVE
    item_type: Optional[ItemType] = None
    description: Optional[str] = None
    tags: List[str] = []


class ItemDetail(CLIModel):
    """Detailed item model returned by get commands.

    Extends Item with additional detail fields that are
    only available when fetching a single item.
    """

    # Read-only field: server-assigned, immutable
    id: str = Field(frozen=True)

    # Regular required field
    name: str

    # Optional fields from Item
    status: ItemStatus = ItemStatus.ACTIVE
    item_type: Optional[ItemType] = None
    description: Optional[str] = None
    tags: List[str] = []

    # Read-only timestamp fields: server-assigned
    created_at: Optional[str] = Field(default=None, frozen=True)
    updated_at: Optional[str] = Field(default=None, frozen=True)
    created_by: Optional[str] = Field(default=None, frozen=True)
    metadata: Optional[dict] = None


# ==================== Factory Functions ====================
# Use factory functions for polymorphic model creation


def create_item(data: dict) -> Item:
    """Create an Item model from scraped page data.

    Args:
        data: Raw dict from page scraping

    Returns:
        Item model instance

    Raises:
        ValidationError: If required fields are missing
    """
    return Item(**data)


def create_item_detail(data: dict) -> ItemDetail:
    """Create an ItemDetail model from scraped page data.

    Args:
        data: Raw dict from page scraping

    Returns:
        ItemDetail model instance

    Raises:
        ValidationError: If required fields are missing
    """
    return ItemDetail(**data)
