"""WordPress CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.

Model Architecture:
- CLIModel: Base class with CLI-friendly configuration
- Post: Base model for list commands (minimal fields, read-only id)
- PostDetail: Extended model for get commands (all fields, read-only timestamps)
- PostCreate: Model for POST payloads (writable fields only)
- PostUpdate: Model for PATCH payloads (all fields optional)
- Media: Model for media library items

Read-Only Fields:
- Use Field(frozen=True) for immutable fields (id, timestamps)
- Use Field(exclude=True) to exclude from model_dump()
- Use Field(init=False) to exclude from __init__

Usage:
    from .models import Post, PostDetail, PostCreate, create_post

    # Create from API response
    post = create_post(api_response)

    # Access typed fields
    print(post.title)
    print(post.status.value)

    # Serialize to JSON
    print_json(post)
"""
from .base import CLIModel
from .post import (
    # Models
    Post,
    PostDetail,
    PostCreate,
    PostUpdate,
    Page,
    PageDetail,
    Media,
    Category,
    CategoryCreate,
    CategoryUpdate,
    Tag,
    TagCreate,
    TagUpdate,
    # Enums
    PostStatus,
    PostFormat,
    # Factory functions
    create_post,
    create_post_detail,
    create_page,
    create_page_detail,
    create_media,
    create_category,
    create_tag,
)
from .plugin import Plugin, create_plugin

__all__ = [
    # Base
    "CLIModel",
    # Models
    "Post",
    "PostDetail",
    "PostCreate",
    "PostUpdate",
    "Page",
    "PageDetail",
    "Media",
    "Category",
    "CategoryCreate",
    "CategoryUpdate",
    "Tag",
    "TagCreate",
    "TagUpdate",
    "Plugin",
    # Enums
    "PostStatus",
    "PostFormat",
    # Factory functions
    "create_post",
    "create_post_detail",
    "create_page",
    "create_page_detail",
    "create_media",
    "create_category",
    "create_tag",
    "create_plugin",
]
