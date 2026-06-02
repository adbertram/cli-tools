"""Purge result models for Cloudflare CLI.

Models for cache purge operation responses.
"""
from pydantic import Field

from .base import CLIModel


class PurgeResult(CLIModel):
    """Result model for cache purge operations.

    Cloudflare returns a simple response with an ID confirming the purge.
    """

    # Purge operation ID
    id: str = Field(frozen=True)


def create_purge_result(data: dict) -> PurgeResult:
    """Create a PurgeResult model from API response data.

    Args:
        data: Raw dict from API response

    Returns:
        PurgeResult model instance

    Raises:
        ValidationError: If required fields are missing
    """
    return PurgeResult(**data)
