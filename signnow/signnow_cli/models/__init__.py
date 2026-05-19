"""Signnow CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.

Model Architecture:
- CLIModel: Base class with CLI-friendly configuration
- Item: Base model for list commands (minimal fields, read-only id)
- ItemDetail: Extended model for get commands (all fields, read-only timestamps)
- ItemCreate: Model for POST payloads (writable fields only)
- ItemUpdate: Model for PATCH payloads (all fields optional)

Read-Only Fields:
- Use Field(frozen=True) for immutable fields (id, timestamps)
- Use Field(exclude=True) to exclude from model_dump()
- Use Field(init=False) to exclude from __init__

Usage:
    from .models import Item, ItemDetail, ItemCreate, create_item

    # Create from API response
    item = create_item(api_response)

    # Access typed fields
    print(item.name)
    print(item.status.value)

    # Serialize to JSON
    print_json(item)
"""
from .base import CLIModel
from .ai_instruction import AIInstruction
from .item import (
    # Models
    Item,
    ItemDetail,
    ItemCreate,
    ItemUpdate,
    # Enums
    ItemStatus,
    ItemType,
    # Factory functions
    create_item,
    create_item_detail,
)

__all__ = [
    # Base
    "AIInstruction",
    "CLIModel",
    # Models
    "Item",
    "ItemDetail",
    "ItemCreate",
    "ItemUpdate",
    # Enums
    "ItemStatus",
    "ItemType",
    # Factory functions
    "create_item",
    "create_item_detail",
]
