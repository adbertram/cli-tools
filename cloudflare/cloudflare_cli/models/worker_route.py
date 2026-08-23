"""Worker route models for Cloudflare CLI.

Worker routes map URL patterns in a zone to Workers scripts. Routes are
zone-scoped (unlike scripts, which are account-scoped).
"""
from typing import Optional

from pydantic import Field

from .base import CLIModel


class WorkerRoute(CLIModel):
    """Route model returned by Workers routes commands."""

    # Read-only field: server-assigned
    id: str = Field(frozen=True)

    # URL pattern to match incoming requests against
    pattern: str

    # Name of the script to run if the route matches
    script: Optional[str] = None


def create_worker_route(data: dict) -> WorkerRoute:
    """Create a WorkerRoute model from API response data.

    Args:
        data: Raw dict from API response

    Returns:
        WorkerRoute model instance

    Raises:
        ValidationError: If required fields are missing
    """
    return WorkerRoute(**data)
