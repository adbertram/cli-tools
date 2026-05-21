"""Configuration management for Airtable CLI."""
import os
from pathlib import Path
from typing import Optional

import requests

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for Airtable CLI (Personal Access Token authentication)."""

    DIST_NAME = "airtable-cli"

    CREDENTIAL_TYPES = [CredentialType.PERSONAL_ACCESS_TOKEN]
    DEFAULT_BASE_URL = "https://api.airtable.com/v0"
    ROOT_CONFIG_FIELDS = ("BASE_ID",)

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def default_base_id(self) -> Optional[str]:
        """Get default Airtable base ID."""
        return self._get("BASE_ID")

    @property
    def storage_dir(self) -> Path:
        """Get storage directory for the active profile (used by cache commands and the @cached decorator)."""
        return self.get_profile_data_dir()

    def test_connection(self):
        """Test Airtable API connectivity with a lightweight whoami call."""
        try:
            response = requests.get(
                f"{self.base_url}/meta/whoami",
                headers={"Authorization": f"Bearer {self.personal_access_token}"},
            )
            if response.ok:
                return {"api_test": "passed"}
            return {"api_test": f"failed: {response.status_code} {response.text}"}
        except Exception as e:
            return {"api_test": f"failed: {e}"}


_configs = {}


def get_config(profile=None):
    """Get or create a Config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
