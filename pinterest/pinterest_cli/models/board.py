"""Pinterest board models."""

from enum import Enum
from typing import Optional

from .base import CLIModel


class BoardPrivacy(str, Enum):
    """Pinterest board privacy levels."""

    PUBLIC = "PUBLIC"
    PROTECTED = "PROTECTED"
    SECRET = "SECRET"


class BoardMedia(CLIModel):
    """Pinterest board media summary."""

    image_cover_url: Optional[str] = None
    pin_thumbnail_urls: Optional[list[str]] = None


class Board(CLIModel):
    """Pinterest board summary."""

    id: str
    name: str
    privacy: Optional[BoardPrivacy] = None
    description: Optional[str] = None
    created_at: Optional[str] = None
    board_pins_modified_at: Optional[str] = None
    collaborator_count: Optional[int] = None
    follower_count: Optional[int] = None
    is_ads_only: Optional[bool] = None
    media: Optional[BoardMedia] = None
