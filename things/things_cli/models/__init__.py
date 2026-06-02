"""Things CLI models.

All entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.

Models map to Things 3 SQLite database tables:
- Task: TMTask (type=0) - To-do items
- Project: TMTask (type=1) - Projects
- Area: TMArea - Areas/categories
- Tag: TMTag - Tags with hierarchy
- ChecklistItem: TMChecklistItem - Checklist items within tasks
"""
from .base import CLIModel
from .item import (
    # Enums
    TaskType,
    TaskStatus,
    StartType,
    # Models
    Task,
    Project,
    Area,
    Tag,
    ChecklistItem,
    AuthStatus,
    # Factory functions
    create_task,
    create_project,
    create_area,
    create_tag,
    # Legacy aliases (template compatibility)
    Item,
    ItemDetail,
    ItemStatus,
    ItemType,
    ItemCreate,
    ItemUpdate,
    create_item,
    create_item_detail,
)

__all__ = [
    # Base
    "CLIModel",
    # Enums
    "TaskType",
    "TaskStatus",
    "StartType",
    # Models
    "Task",
    "Project",
    "Area",
    "Tag",
    "ChecklistItem",
    "AuthStatus",
    # Factory functions
    "create_task",
    "create_project",
    "create_area",
    "create_tag",
    # Legacy aliases
    "Item",
    "ItemDetail",
    "ItemStatus",
    "ItemType",
    "ItemCreate",
    "ItemUpdate",
    "create_item",
    "create_item_detail",
]
