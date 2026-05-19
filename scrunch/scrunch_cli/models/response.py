"""Response models for Scrunch CLI."""
from typing import Any, Dict, List, Optional

from .base import CLIModel


class ResponseListing(CLIModel):
    """AI response data with evaluation scores, citations, and competitor analysis."""

    id: Optional[int] = None
    prompt_id: Optional[int] = None
    persona_id: Optional[int] = None
    platform: Optional[str] = None
    stage: Optional[str] = None
    text: Optional[str] = None
    brand_mentioned: Optional[bool] = None
    brand_sentiment: Optional[str] = None
    brand_position: Optional[int] = None
    citations: Optional[List[dict]] = None
    competitors: Optional[List[dict]] = None
    sources: Optional[List[dict]] = None
    date: Optional[str] = None
    has_shopping_data: Optional[bool] = None
    metadata: Optional[dict] = None


def create_response_listing(data: dict) -> ResponseListing:
    """Create a ResponseListing model from API response data."""
    return ResponseListing(**data)
