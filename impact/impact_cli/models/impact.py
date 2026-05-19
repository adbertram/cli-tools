"""Generic Impact response models."""
from typing import Any

from pydantic import ConfigDict, Field

from .base import CLIModel


class ImpactResource(CLIModel):
    """Impact API object that preserves every returned field."""

    model_config = ConfigDict(extra="allow")


class ImpactValue(CLIModel):
    """Non-object API response value."""

    value: Any


class ImpactDownload(CLIModel):
    """Downloaded file or redirect response metadata."""

    status_code: int = Field(frozen=True)
    content_type: str = Field(frozen=True)
    content: str = Field(frozen=True)


def create_resource(data: dict[str, Any]) -> ImpactResource:
    """Create a generic Impact resource from an API object."""
    return ImpactResource(**data)


def create_value(value: Any) -> ImpactValue:
    """Create a generic scalar/list wrapper."""
    return ImpactValue(value=value)
