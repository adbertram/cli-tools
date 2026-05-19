"""Photo models for photos-app CLI.

Models represent photo/video assets from the macOS Photos library.
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import Field

from .base import CLIModel


# ==================== Enums ====================


class AssetKind(str, Enum):
    """Asset type values."""

    PHOTO = "photo"
    VIDEO = "video"


class CloudStatus(str, Enum):
    """iCloud sync status values."""

    LOCAL = "local"
    ICLOUD = "icloud"


# ==================== Models ====================


class Photo(CLIModel):
    """Represents a photo/video asset from the Photos library.

    Required fields:
    - uuid: Unique identifier for the asset
    - filename: Original or current filename

    Optional fields provide additional metadata when available.
    """

    # Read-only field: database-assigned, immutable
    uuid: str = Field(frozen=True)

    # Required field
    filename: str

    # Optional metadata fields
    date_created: Optional[datetime] = None
    date_added: Optional[datetime] = None
    kind: AssetKind = AssetKind.PHOTO
    file_type: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    cloud_status: CloudStatus = CloudStatus.ICLOUD
    is_favorite: bool = False
    is_hidden: bool = False

    def to_dict(self, **kwargs) -> dict:
        """Include standard id/name aliases."""
        d = super().to_dict(**kwargs)
        d["id"] = d["uuid"]
        d["name"] = d["filename"]
        return d


class Album(CLIModel):
    """Represents an album from the Photos library.

    Required fields:
    - uuid: Unique identifier for the album
    - title: Album name

    Optional fields provide additional metadata when available.
    """

    # Read-only field: database-assigned, immutable
    uuid: str = Field(frozen=True)

    # Required field
    title: str

    # Optional metadata fields
    photo_count: int = 0
    video_count: int = 0
    date_created: Optional[datetime] = None

    def to_dict(self, **kwargs) -> dict:
        """Include standard id/name aliases."""
        d = super().to_dict(**kwargs)
        d["id"] = d["uuid"]
        d["name"] = d["title"]
        return d


# ==================== Factory Functions ====================


def create_album(data: dict) -> Album:
    """Create an Album model from database query results.

    Args:
        data: Raw dict from SQLite query

    Returns:
        Album model instance

    Raises:
        ValidationError: If required fields are missing
    """
    return Album(**data)


def create_photo(data: dict) -> Photo:
    """Create a Photo model from database query results.

    Args:
        data: Raw dict from SQLite query

    Returns:
        Photo model instance

    Raises:
        ValidationError: If required fields are missing
    """
    return Photo(**data)
