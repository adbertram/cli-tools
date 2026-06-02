"""YouTube Data API v3 video models."""
from enum import Enum
from typing import List, Optional

from .base import CLIModel


class PrivacyStatus(str, Enum):
    """YouTube video privacy status."""

    PRIVATE = "private"
    UNLISTED = "unlisted"
    PUBLIC = "public"


class Video(CLIModel):
    """YouTube video summary (used in list output)."""

    id: str
    title: str
    description: Optional[str] = None
    published_at: Optional[str] = None
    privacy_status: Optional[PrivacyStatus] = None
    channel_id: Optional[str] = None


class VideoStatistics(CLIModel):
    """YouTube video statistics."""

    view_count: Optional[int] = None
    like_count: Optional[int] = None
    comment_count: Optional[int] = None
    favorite_count: Optional[int] = None


class VideoStatus(CLIModel):
    """YouTube video status block."""

    upload_status: Optional[str] = None
    privacy_status: Optional[PrivacyStatus] = None
    license: Optional[str] = None
    embeddable: Optional[bool] = None
    public_stats_viewable: Optional[bool] = None
    made_for_kids: Optional[bool] = None
    publish_at: Optional[str] = None


class VideoDetail(CLIModel):
    """Full YouTube video metadata (used in get output)."""

    id: str
    title: str
    description: Optional[str] = None
    published_at: Optional[str] = None
    channel_id: Optional[str] = None
    channel_title: Optional[str] = None
    tags: Optional[List[str]] = None
    category_id: Optional[str] = None
    duration: Optional[str] = None
    thumbnail_url: Optional[str] = None
    statistics: Optional[VideoStatistics] = None
    status: Optional[VideoStatus] = None


class UploadResult(CLIModel):
    """Result of a video upload."""

    id: str
    title: str
    privacy_status: PrivacyStatus
    publish_at: Optional[str] = None
    url: str
    thumbnail_uploaded: bool = False


class UpdateResult(CLIModel):
    """Result of a video update."""

    id: str
    title: str
    privacy_status: Optional[PrivacyStatus] = None
    thumbnail_updated: bool = False


class DeleteResult(CLIModel):
    """Result of a video delete."""

    id: str
    deleted: bool
