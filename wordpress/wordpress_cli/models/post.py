"""WordPress models for WordPress CLI.

Model Design Principles:
- Required fields have no default value (Pydantic enforces presence)
- Optional fields use Optional[Type] = None
- Use enums for fields with fixed value sets
- Create specific model subclasses for different entity types
"""
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import Field

from .base import CLIModel


# ==================== Enums ====================


class PostStatus(str, Enum):
    """Post status values for WordPress."""

    PUBLISH = "publish"
    FUTURE = "future"
    DRAFT = "draft"
    PENDING = "pending"
    PRIVATE = "private"
    TRASH = "trash"


class PostFormat(str, Enum):
    """Post format types for WordPress."""

    STANDARD = "standard"
    ASIDE = "aside"
    GALLERY = "gallery"
    LINK = "link"
    IMAGE = "image"
    QUOTE = "quote"
    STATUS = "status"
    VIDEO = "video"
    AUDIO = "audio"
    CHAT = "chat"


# ==================== Post Models ====================


class Post(CLIModel):
    """Base post model returned by list commands.

    Required fields:
    - id: Unique identifier (server-assigned, read-only)
    - title: Post title

    Optional fields have defaults and can be omitted.
    """

    # Read-only field: server-assigned, immutable
    id: int = Field(frozen=True)

    # Title is stored as rendered HTML in WordPress API
    title: str

    # Optional fields
    status: PostStatus = PostStatus.DRAFT
    slug: Optional[str] = None
    date: Optional[str] = Field(default=None, frozen=True)
    modified: Optional[str] = Field(default=None, frozen=True)
    link: Optional[str] = Field(default=None, frozen=True)
    author: Optional[int] = None


class PostDetail(CLIModel):
    """Detailed post model returned by get commands.

    Extends Post with additional detail fields that are
    only available when fetching a single post.
    """

    # Read-only field: server-assigned, immutable
    id: int = Field(frozen=True)

    # Required field
    title: str

    # Optional fields from Post
    status: PostStatus = PostStatus.DRAFT
    slug: Optional[str] = None
    date: Optional[str] = Field(default=None, frozen=True)
    modified: Optional[str] = Field(default=None, frozen=True)
    link: Optional[str] = Field(default=None, frozen=True)
    author: Optional[int] = None

    # Additional detail fields
    content: Optional[str] = None
    excerpt: Optional[str] = None
    featured_media: Optional[int] = None
    comment_status: Optional[str] = "open"
    ping_status: Optional[str] = "open"
    format: Optional[PostFormat] = PostFormat.STANDARD
    sticky: bool = False
    categories: List[int] = []
    tags: List[int] = []
    meta: Optional[Dict[str, Any]] = None


class PostCreate(CLIModel):
    """Model for creating new posts.

    Only includes writable fields - no id or timestamps.
    Use this for POST request payloads.
    """

    title: str
    content: Optional[str] = None
    status: PostStatus = PostStatus.DRAFT
    slug: Optional[str] = None
    excerpt: Optional[str] = None
    author: Optional[int] = None
    featured_media: Optional[int] = None
    comment_status: Optional[str] = "open"
    ping_status: Optional[str] = "open"
    format: Optional[PostFormat] = PostFormat.STANDARD
    sticky: bool = False
    categories: List[int] = []
    tags: List[int] = []


class PostUpdate(CLIModel):
    """Model for updating posts.

    All fields optional - only send what needs to change.
    Use this for PATCH/POST request payloads.
    """

    title: Optional[str] = None
    content: Optional[str] = None
    status: Optional[PostStatus] = None
    slug: Optional[str] = None
    excerpt: Optional[str] = None
    author: Optional[int] = None
    featured_media: Optional[int] = None
    comment_status: Optional[str] = None
    ping_status: Optional[str] = None
    format: Optional[PostFormat] = None
    sticky: Optional[bool] = None
    categories: Optional[List[int]] = None
    tags: Optional[List[int]] = None


# ==================== Media Models ====================


class Media(CLIModel):
    """Media item model for WordPress media library."""

    # Read-only field: server-assigned, immutable
    id: int = Field(frozen=True)

    # Required fields
    title: str
    source_url: str = Field(frozen=True)

    # Optional fields
    date: Optional[str] = Field(default=None, frozen=True)
    modified: Optional[str] = Field(default=None, frozen=True)
    slug: Optional[str] = None
    author: Optional[int] = None
    media_type: Optional[str] = None
    mime_type: Optional[str] = None
    alt_text: Optional[str] = None
    caption: Optional[str] = None
    description: Optional[str] = None


# ==================== Factory Functions ====================


def create_post(data: dict) -> Post:
    """Create a Post model from API response data.

    Args:
        data: Raw dict from API response

    Returns:
        Post model instance

    Raises:
        ValidationError: If required fields are missing
    """
    # Extract rendered title from WordPress API format
    if "title" in data and isinstance(data["title"], dict):
        data["title"] = data["title"].get("rendered", "")

    return Post(**data)


def create_post_detail(data: dict, raw: bool = False) -> PostDetail:
    """Create a PostDetail model from API response data.

    Args:
        data: Raw dict from API response
        raw: If True, extract raw content (Gutenberg blocks) instead of rendered HTML

    Returns:
        PostDetail model instance

    Raises:
        ValidationError: If required fields are missing
    """
    # Extract rendered or raw fields from WordPress API format
    content_key = "raw" if raw else "rendered"

    if "title" in data and isinstance(data["title"], dict):
        data["title"] = data["title"].get("raw" if raw else "rendered", "")

    if "content" in data and isinstance(data["content"], dict):
        data["content"] = data["content"].get(content_key, "")

    if "excerpt" in data and isinstance(data["excerpt"], dict):
        data["excerpt"] = data["excerpt"].get(content_key, "")

    return PostDetail(**data)


def create_media(data: dict) -> Media:
    """Create a Media model from API response data.

    Args:
        data: Raw dict from API response

    Returns:
        Media model instance

    Raises:
        ValidationError: If required fields are missing
    """
    # Extract rendered fields from WordPress API format
    if "title" in data and isinstance(data["title"], dict):
        data["title"] = data["title"].get("rendered", "")

    if "caption" in data and isinstance(data["caption"], dict):
        data["caption"] = data["caption"].get("rendered", "")

    if "description" in data and isinstance(data["description"], dict):
        data["description"] = data["description"].get("rendered", "")

    return Media(**data)


# ==================== Page Models ====================


class Page(CLIModel):
    """Base page model returned by list commands.

    Pages are like posts but support hierarchy (parent, menu_order, template)
    and do not have tags, categories, or post formats.
    """

    id: int = Field(frozen=True)
    title: str

    status: PostStatus = PostStatus.DRAFT
    slug: Optional[str] = None
    date: Optional[str] = Field(default=None, frozen=True)
    modified: Optional[str] = Field(default=None, frozen=True)
    link: Optional[str] = Field(default=None, frozen=True)
    author: Optional[int] = None
    parent: int = 0
    menu_order: int = 0


class PageDetail(CLIModel):
    """Detailed page model returned by get commands."""

    id: int = Field(frozen=True)
    title: str

    status: PostStatus = PostStatus.DRAFT
    slug: Optional[str] = None
    date: Optional[str] = Field(default=None, frozen=True)
    modified: Optional[str] = Field(default=None, frozen=True)
    link: Optional[str] = Field(default=None, frozen=True)
    author: Optional[int] = None

    content: Optional[str] = None
    excerpt: Optional[str] = None
    featured_media: Optional[int] = None
    comment_status: Optional[str] = "closed"
    ping_status: Optional[str] = "closed"
    parent: int = 0
    menu_order: int = 0
    template: Optional[str] = ""
    meta: Optional[Dict[str, Any]] = None


def create_page(data: dict) -> Page:
    """Create a Page model from API response data."""
    if "title" in data and isinstance(data["title"], dict):
        data["title"] = data["title"].get("rendered", "")
    return Page(**data)


def create_page_detail(data: dict, raw: bool = False) -> PageDetail:
    """Create a PageDetail model from API response data.

    Args:
        data: Raw dict from API response
        raw: If True, extract raw content (Gutenberg blocks) instead of rendered HTML
    """
    content_key = "raw" if raw else "rendered"

    if "title" in data and isinstance(data["title"], dict):
        data["title"] = data["title"].get("raw" if raw else "rendered", "")

    if "content" in data and isinstance(data["content"], dict):
        data["content"] = data["content"].get(content_key, "")

    if "excerpt" in data and isinstance(data["excerpt"], dict):
        data["excerpt"] = data["excerpt"].get(content_key, "")

    return PageDetail(**data)


# ==================== Category Models ====================


class Category(CLIModel):
    """Category model for WordPress categories."""

    # Read-only field: server-assigned, immutable
    id: int = Field(frozen=True)

    # Required fields
    name: str

    # Optional fields
    slug: Optional[str] = None
    description: Optional[str] = None
    parent: int = 0
    count: int = Field(default=0, frozen=True)
    link: Optional[str] = Field(default=None, frozen=True)


class CategoryCreate(CLIModel):
    """Model for creating new categories.

    Only includes writable fields - no id.
    Use this for POST request payloads.
    """

    name: str
    slug: Optional[str] = None
    description: Optional[str] = None
    parent: int = 0


class CategoryUpdate(CLIModel):
    """Model for updating categories.

    All fields optional - only send what needs to change.
    Use this for PATCH/POST request payloads.
    """

    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    parent: Optional[int] = None


def create_category(data: dict) -> Category:
    """Create a Category model from API response data.

    Args:
        data: Raw dict from API response

    Returns:
        Category model instance

    Raises:
        ValidationError: If required fields are missing
    """
    return Category(**data)


# ==================== Tag Models ====================


class Tag(CLIModel):
    """Tag model for WordPress tags."""

    # Read-only field: server-assigned, immutable
    id: int = Field(frozen=True)

    # Required fields
    name: str

    # Optional fields
    slug: Optional[str] = None
    description: Optional[str] = None
    count: int = Field(default=0, frozen=True)
    link: Optional[str] = Field(default=None, frozen=True)


class TagCreate(CLIModel):
    """Model for creating new tags.

    Only includes writable fields - no id.
    Use this for POST request payloads.
    """

    name: str
    slug: Optional[str] = None
    description: Optional[str] = None


class TagUpdate(CLIModel):
    """Model for updating tags.

    All fields optional - only send what needs to change.
    Use this for PATCH/POST request payloads.
    """

    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None


def create_tag(data: dict) -> Tag:
    """Create a Tag model from API response data.

    Args:
        data: Raw dict from API response

    Returns:
        Tag model instance

    Raises:
        ValidationError: If required fields are missing
    """
    return Tag(**data)
