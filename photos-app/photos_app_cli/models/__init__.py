"""photos-app CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.

Model Architecture:
- CLIModel: Base class with CLI-friendly configuration
- Photo: Model for photo/video assets from Photos library
- Album: Model for albums from Photos library

Usage:
    from .models import Photo, Album, AssetKind, CloudStatus, create_photo

    # Create from database query
    photo = create_photo(row_data)
    album = create_album(row_data)

    # Access typed fields
    print(photo.uuid)
    print(photo.kind.value)

    # Serialize to JSON
    print_json(photo)
"""
from .base import CLIModel
from .item import (
    # Models
    Photo,
    Album,
    # Enums
    AssetKind,
    CloudStatus,
    # Factory functions
    create_photo,
    create_album,
)

__all__ = [
    # Base
    "CLIModel",
    # Models
    "Photo",
    "Album",
    # Enums
    "AssetKind",
    "CloudStatus",
    # Factory functions
    "create_photo",
    "create_album",
]
