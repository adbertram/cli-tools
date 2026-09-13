"""Image model for eBay CLI."""
from typing import Optional

from pydantic import Field, HttpUrl

from .base import EbayBaseModel

# eBay allows up to 24 images for an ordinary listing. The 12-image limit applies
# only to individual variations, which this CLI does not create.
MAX_IMAGES_PER_LISTING = 24


class Image(EbayBaseModel):
    """Image associated with a listing."""

    url: str = Field(..., description="eBay-hosted image URL")
    thumbnail_url: Optional[str] = Field(None, description="Thumbnail version URL")
    position: int = Field(
        0,
        ge=0,
        le=MAX_IMAGES_PER_LISTING - 1,
        description="Order position (0-indexed, max 23)",
    )
    source: Optional[str] = Field(
        None,
        description="Image source type",
        pattern="^(local_file|url|photos_album)$",
    )
    original_path: Optional[str] = Field(None, description="Original file path or URL")


class ImageUploadResponse(EbayBaseModel):
    """Response from eBay Media API image upload."""

    image_id: str = Field(..., alias="imageId", description="eBay image ID")
    image_url: str = Field(..., alias="imageUrl", description="Hosted image URL")
    expiration_date: str = Field(..., alias="expirationDate", description="When the image expires")
