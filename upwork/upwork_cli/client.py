"""Upwork profile client."""

from __future__ import annotations

from typing import Optional

from cli_tools_shared.auth import BrowserAutomation
from cli_tools_shared.exceptions import ClientError

from .browser import UpworkBrowser
from .parsers import (
    editable_profile_fields,
    field_definition,
    normalize_profile_updates,
)

PROFILE_DISABLED_MESSAGE = (
    "Upwork live profile read/update is disabled because Upwork's Cloudflare "
    "challenge blocks non-headed automation. Metadata commands and "
    "'profile update --dry-run' still work."
)


class UpworkClient:
    """Client for supported and disabled profile operations."""

    browser_automation_class: type[BrowserAutomation] = UpworkBrowser

    def close(self):
        return None

    def get_profile(self) -> dict:
        """Report disabled live profile reads."""
        raise ClientError(PROFILE_DISABLED_MESSAGE)

    def list_profile_fields(self) -> list[dict]:
        """Return supported profile fields with empty live values."""
        rows = []
        for field in editable_profile_fields(include_read_only=True):
            row = dict(field)
            row["value"] = None
            rows.append(row)
        return rows

    def get_profile_field(self, name: str) -> dict:
        """Return one supported profile field with an empty live value."""
        row = field_definition(name)
        row["value"] = None
        return row

    def update_profile(self, updates: dict) -> dict:
        """Validate updates, then report disabled live profile writes."""
        normalize_profile_updates(updates)
        raise ClientError(PROFILE_DISABLED_MESSAGE)


_client: Optional[UpworkClient] = None


def get_client() -> UpworkClient:
    """Get or create the global Upwork client instance."""
    global _client
    if _client is None:
        _client = UpworkClient()
    return _client
