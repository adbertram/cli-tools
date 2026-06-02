"""Plugin models for WordPress CLI."""
from typing import Optional

from pydantic import Field

from .base import CLIModel


class Plugin(CLIModel):
    """WordPress plugin model from REST API."""

    plugin: str = Field(frozen=True)  # e.g. "mailchimp-for-wp/mailchimp-for-wp.php"
    status: str  # "active" or "inactive"
    name: str
    version: str
    author: Optional[str] = None
    description: Optional[str] = None
    plugin_uri: Optional[str] = None
    network_only: bool = False
    requires_wp: Optional[str] = None
    requires_php: Optional[str] = None
    textdomain: Optional[str] = None
    auto_update: bool = False
    update_status: Optional[str] = None
    update_version: Optional[str] = None
    latest_version: Optional[str] = None
    latest_version_source: Optional[str] = None


def create_plugin(data: dict) -> Plugin:
    """Create a Plugin model from API response data.

    Handles nested description field (WordPress returns {raw, rendered}).
    """
    # Flatten description if nested
    desc = data.get("description")
    if isinstance(desc, dict):
        data = {**data, "description": desc.get("raw", desc.get("rendered", ""))}

    return Plugin(**data)
