"""Progress ServiceNow CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.
"""
from .base import CLIModel
from .item import (
    Item,
    ItemDetail,
    ItemStatus,
    ItemType,
    create_item,
    create_item_detail,
)
from .ticket import (
    Ticket,
    TicketDetail,
    TicketState,
    TicketPriority,
    TicketView,
    Comment,
    CatalogItem,
)

__all__ = [
    # Base
    "CLIModel",
    # Generic models (scaffolded)
    "Item",
    "ItemDetail",
    "ItemStatus",
    "ItemType",
    "create_item",
    "create_item_detail",
    # ServiceNow ticket models
    "Ticket",
    "TicketDetail",
    "TicketState",
    "TicketPriority",
    "TicketView",
    "Comment",
    "CatalogItem",
]
