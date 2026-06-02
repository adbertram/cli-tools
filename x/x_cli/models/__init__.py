"""X CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.

Usage:
    from .models import Tweet, create_tweet

    # Create from API response
    tweet = create_tweet(api_response)

    # Access typed fields
    print(tweet.id)
    print(tweet.text)
"""
from .base import CLIModel
from .tweet import (
    Tweet,
    PublicMetrics,
    create_tweet,
)

__all__ = [
    # Base
    "CLIModel",
    # Models
    "Tweet",
    "PublicMetrics",
    # Factory functions
    "create_tweet",
]
