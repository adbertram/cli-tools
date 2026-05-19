"""Brand models for Scrunch CLI."""
from typing import List, Optional

from .base import CLIModel


class Brand(CLIModel):
    """Brand model returned by the API."""

    id: int
    name: str
    description: Optional[str] = None
    website: Optional[str] = None
    status: Optional[str] = None
    alternative_websites: List[str] = []
    competitors: List[dict] = []
    personas: List[dict] = []
    key_topics: List[str] = []


class CreateBrand(CLIModel):
    """Model for creating a new brand."""

    name: str
    website: str
    description: str
    alternative_names: Optional[List[str]] = None
    alternative_websites: Optional[List[str]] = None
    competitors: Optional[List[dict]] = None
    personas: Optional[List[dict]] = None
    key_topics: Optional[List[str]] = None
    status: Optional[str] = None


class UpdateBrand(CLIModel):
    """Model for updating a brand."""

    name: Optional[str] = None
    website: Optional[str] = None
    description: Optional[str] = None
    alternative_names: Optional[List[str]] = None
    alternative_websites: Optional[List[str]] = None
    competitors: Optional[List[dict]] = None
    personas: Optional[List[dict]] = None
    key_topics: Optional[List[str]] = None
    status: Optional[str] = None


def create_brand(data: dict) -> Brand:
    """Create a Brand model from API response data."""
    return Brand(**data)
