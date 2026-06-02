"""Configuration management for dev_to CLI."""

from __future__ import annotations

from pathlib import Path

import requests
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType

from . import __version__

API_ACCEPT_HEADER = "application/vnd.forem.api-v1+json"

DEFAULT_USER_AGENT = f"dev_to-cli/{__version__}"


class Config(BaseConfig):
    """Config for the DEV Community CLI."""

    DIST_NAME = "dev_to-cli"
    CREDENTIAL_TYPES = [CredentialType.API_KEY]
    DEFAULT_BASE_URL = "https://dev.to/api"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def storage_dir(self) -> Path:
        """Directory used by the shared response cache."""
        return self.get_profile_data_dir()

    def test_connection(self):
        """Verify the saved API key against the authenticated-user endpoint."""
        response = requests.get(
            f"{self.base_url.rstrip('/')}/users/me",
            headers={
                "Accept": API_ACCEPT_HEADER,
                "User-Agent": DEFAULT_USER_AGENT,
                "api-key": self.api_key,
            },
            timeout=15,
        )
        if 200 <= response.status_code < 300:
            return {"api_test": "passed"}
        return {"api_test": f"failed: HTTP {response.status_code}"}


_configs = {}
_global_profile = None


def get_config(profile=None):
    """Return the cached config for the requested profile."""
    effective_profile = profile if profile is not None else _global_profile
    key = effective_profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=effective_profile)
    return _configs[key]


def set_global_profile(profile=None):
    """Set the profile used by CLI-created configs."""
    global _global_profile
    _global_profile = profile
