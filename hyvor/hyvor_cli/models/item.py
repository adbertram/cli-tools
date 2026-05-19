"""Comment models for Hyvor CLI.

Hyvor Talk API models for managing comments and discussions.
Models accept ALL fields from the API response (extra="allow").
"""
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import ConfigDict

from .base import CLIModel


# ==================== Enums ====================


class CommentStatus(str, Enum):
    """Status values for comments."""

    APPROVED = "approved"
    PENDING = "pending"
    SPAM = "spam"
    REJECTED = "rejected"
    TRASH = "trash"


# ==================== User & Page Models ====================


class User(CLIModel):
    """User model - accepts all API fields."""

    model_config = ConfigDict(extra="allow")

    id: Optional[int] = None
    name: Optional[str] = None
    type: Optional[str] = None
    htid: Optional[str] = None
    username: Optional[str] = None
    email: Optional[str] = None
    picture_url: Optional[str] = None
    bio: Optional[str] = None
    location: Optional[str] = None
    website_url: Optional[str] = None
    created_at: Optional[int] = None
    last_commented_at: Optional[int] = None
    comments_count: Optional[int] = None
    state: Optional[str] = None
    reputation: Optional[int] = None
    role: Optional[str] = None


class Page(CLIModel):
    """Page model - accepts all API fields."""

    model_config = ConfigDict(extra="allow")

    id: Optional[int] = None
    title: Optional[str] = None
    url: Optional[str] = None
    identifier: Optional[str] = None
    created_at: Optional[int] = None
    last_commented_at: Optional[int] = None
    is_closed: Optional[bool] = None
    is_premoderation_on: Optional[bool] = None
    author_email: Optional[str] = None
    comments_count: Optional[int] = None
    ratings: Optional[Dict[str, Any]] = None
    reactions: Optional[Dict[str, Any]] = None


# ==================== Comment Models ====================


class Comment(CLIModel):
    """Comment model - accepts all API fields."""

    model_config = ConfigDict(extra="allow")

    id: int
    body_html: Optional[str] = None
    body: Optional[str] = None
    created_at: Optional[int] = None
    status: Optional[str] = None
    user: Optional[User] = None
    page: Optional[Page] = None
    parent: Optional[Any] = None  # Can be int ID or full comment object
    ip_address: Optional[str] = None
    is_featured: Optional[bool] = None
    is_loved: Optional[bool] = None
    is_edited: Optional[bool] = None
    has_mod_seen: Optional[bool] = None
    has_mod_replied: Optional[bool] = None
    has_questions: Optional[bool] = None
    has_links: Optional[bool] = None
    has_media: Optional[bool] = None
    is_automatic_spam: Optional[bool] = None
    flags_count: Optional[int] = None
    last_flag_at: Optional[int] = None
    upvotes: Optional[int] = None
    downvotes: Optional[int] = None
    user_vote: Optional[Any] = None
    history: Optional[List[Any]] = None


class CommentDetail(Comment):
    """Detailed comment model - same as Comment, accepts all fields."""
    pass


class CommentCreate(CLIModel):
    """Model for creating new comments or replies."""

    body: str
    parent_id: Optional[int] = None


class CommentUpdate(CLIModel):
    """Model for updating comments."""

    body: Optional[str] = None
    status: Optional[str] = None


# ==================== Factory Functions ====================


def create_comment(data: dict) -> Comment:
    """Create a Comment model from API response data."""
    return Comment(**data)


def create_comment_detail(data: dict) -> CommentDetail:
    """Create a CommentDetail model from API response data."""
    return CommentDetail(**data)
