"""Atlassian CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.

Model Architecture:
- CLIModel: Base class with CLI-friendly configuration
- Item: Base model for list commands (minimal fields)
- ItemDetail: Extended model for get commands (all fields)

Usage:
    from .models import Item, ItemDetail, ItemStatus, create_item

    # Create from scraped data
    item = create_item(scraped_data)

    # Access typed fields
    print(item.name)
    print(item.status.value)

    # Serialize to JSON
    print_json(item)
"""
from .base import CLIModel
from .item import (
    # Models
    Item,
    ItemDetail,
    # Enums
    ItemStatus,
    ItemType,
    # Factory functions
    create_item,
    create_item_detail,
)

__all__ = [
    # Base
    "CLIModel",
    # Models
    "Item",
    "ItemDetail",
    # Enums
    "ItemStatus",
    "ItemType",
    # Factory functions
    "create_item",
    "create_item_detail",
]
