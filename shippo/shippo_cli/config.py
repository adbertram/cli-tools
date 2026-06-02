"""Configuration management for Shippo CLI."""
import os
from pathlib import Path
from typing import Optional

import requests

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for Shippo CLI (API key authentication)."""

    DIST_NAME = "shippo-cli"

    CREDENTIAL_TYPES = [CredentialType.API_KEY]
    DEFAULT_BASE_URL = "https://api.goshippo.com"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    # Default from-address for shipments
    @property
    def from_name(self) -> Optional[str]:
        """Get default sender name."""
        return self._get("FROM_NAME")

    @property
    def from_street1(self) -> Optional[str]:
        """Get default sender street address."""
        return self._get("FROM_STREET1")

    @property
    def from_city(self) -> Optional[str]:
        """Get default sender city."""
        return self._get("FROM_CITY")

    @property
    def from_state(self) -> Optional[str]:
        """Get default sender state."""
        return self._get("FROM_STATE")

    @property
    def from_zip(self) -> Optional[str]:
        """Get default sender ZIP code."""
        return self._get("FROM_ZIP")

    @property
    def from_phone(self) -> Optional[str]:
        """Get default sender phone number."""
        return self._get("FROM_PHONE")

    @property
    def from_email(self) -> Optional[str]:
        """Get default sender email."""
        return self._get("FROM_EMAIL")

    @property
    def from_country(self) -> str:
        """Get default sender country."""
        return self._get("FROM_COUNTRY") or "US"

    def test_connection(self):
        """Test Shippo API connectivity with a lightweight addresses list call."""
        try:
            response = requests.get(
                f"{self.base_url}/addresses",
                headers={"Authorization": f"ShippoToken {self.api_key}"},
                params={"results": 1},
            )
            if response.ok:
                return {"api_test": "passed"}
            return {"api_test": f"failed: {response.status_code} {response.text[:200]}"}
        except Exception as e:
            return {"api_test": f"failed: {e}"}


_configs = {}


def get_config(profile=None):
    """Get or create a Config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
