"""Pinterest pin models."""

from typing import Optional

from .base import CLIModel


class BoardOwner(CLIModel):
    """Owner summary for a board attached to a pin."""

    username: str


class PinMedia(CLIModel):
    """Minimal Pinterest pin media summary."""

    media_type: Optional[str] = None
    images: Optional[dict] = None


class Pin(CLIModel):
    """Pinterest pin summary."""

    id: str
    title: Optional[str] = None
    description: Optional[str] = None
    alt_text: Optional[str] = None
    link: Optional[str] = None
    board_id: Optional[str] = None
    board_owner: Optional[BoardOwner] = None
    board_section_id: Optional[str] = None
    created_at: Optional[str] = None
    creative_type: Optional[str] = None
    dominant_color: Optional[str] = None
    has_been_promoted: Optional[bool] = None
    is_owner: Optional[bool] = None
    is_product: Optional[bool] = None
    is_standard: Optional[bool] = None
    media: Optional[PinMedia] = None
    note: Optional[str] = None
    parent_pin_id: Optional[str] = None
