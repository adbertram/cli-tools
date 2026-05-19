"""Tweet models for X CLI.

Models for X API v2 tweet objects.
"""
from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import Field

from .base import CLIModel


class PublicMetrics(CLIModel):
    """Public engagement metrics for a tweet."""

    retweet_count: int = 0
    reply_count: int = 0
    like_count: int = 0
    quote_count: int = 0
    bookmark_count: int = 0
    impression_count: int = 0


class Tweet(CLIModel):
    """Tweet model representing a post on X.

    This is the primary model returned when posting or retrieving tweets.
    """

    id: str = Field(frozen=True, description="Unique tweet ID")
    text: str = Field(description="Tweet text content")
    author_id: Optional[str] = Field(default=None, description="Author's user ID")
    created_at: Optional[datetime] = Field(default=None, description="Tweet creation time")
    public_metrics: Optional[PublicMetrics] = Field(
        default=None, description="Public engagement metrics"
    )


def create_tweet(data: Dict[str, Any]) -> Tweet:
    """Create a Tweet model from API response data.

    Args:
        data: Raw API response data

    Returns:
        Tweet model instance
    """
    # Handle public_metrics if present
    if "public_metrics" in data and data["public_metrics"]:
        data["public_metrics"] = PublicMetrics(**data["public_metrics"])

    # Parse created_at if it's a string
    if "created_at" in data and isinstance(data["created_at"], str):
        try:
            data["created_at"] = datetime.fromisoformat(
                data["created_at"].replace("Z", "+00:00")
            )
        except ValueError:
            pass

    return Tweet(**data)
