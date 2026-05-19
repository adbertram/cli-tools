"""AtaBlog CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.

Model Architecture:
- CLIModel: Base class with CLI-friendly configuration
- Item: Base model for list commands (minimal fields)
- ItemDetail: Extended model for get commands (all fields)

Usage:
    from .models import Item, ItemDetail, ItemStatus, create_item

    # Create from parsed CLI output
    item = create_item(parsed_output)

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
from .earnings import (
    PostEarnings,
    create_post_earnings,
)

__all__ = [
    # Base
    "CLIModel",
    # Models
    "Item",
    "ItemDetail",
    "PostEarnings",
    # Enums
    "ItemStatus",
    "ItemType",
    # Factory functions
    "create_item",
    "create_item_detail",
    "create_post_earnings",
]
