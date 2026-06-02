"""Hyvor CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.

Model Architecture:
- CLIModel: Base class with CLI-friendly configuration
- Comment: Base model for list commands (minimal fields, read-only id)
- CommentDetail: Extended model for get commands (all fields, read-only timestamps)
- CommentCreate: Model for POST payloads (writable fields only)
- CommentUpdate: Model for PATCH payloads (all fields optional)

Read-Only Fields:
- Use Field(frozen=True) for immutable fields (id, timestamps)
- Use Field(exclude=True) to exclude from model_dump()
- Use Field(init=False) to exclude from __init__

Usage:
    from .models import Comment, CommentDetail, CommentCreate, create_comment

    # Create from API response
    comment = create_comment(api_response)

    # Access typed fields
    print(comment.body_html)
    print(comment.status.value)

    # Serialize to JSON
    print_json(comment)
"""
from .base import CLIModel
from .item import (
    # Models
    Comment,
    CommentDetail,
    CommentCreate,
    CommentUpdate,
    User,
    Page,
    # Enums
    CommentStatus,
    # Factory functions
    create_comment,
    create_comment_detail,
)

__all__ = [
    # Base
    "CLIModel",
    # Models
    "Comment",
    "CommentDetail",
    "CommentCreate",
    "CommentUpdate",
    "User",
    "Page",
    # Enums
    "CommentStatus",
    # Factory functions
    "create_comment",
    "create_comment_detail",
]
