"""Application models for PartnerStack CLI."""
from typing import Any, Dict, Optional

from pydantic import ConfigDict, Field

from .base import CLIModel


class Application(CLIModel):
    """An application returned by POST /api/v2/applications.

    PartnerStack's reference page documents the request body but does not
    fully enumerate the response schema, so we accept extra fields.
    """

    model_config = ConfigDict(extra="allow")

    key: Optional[str] = Field(default=None)
    group_slug: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None


def create_application(data: Dict[str, Any]) -> Application:
    """Create an Application model from API response data."""
    return Application(**data)
