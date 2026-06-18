"""Configuration management for WP Engine CLI."""

from pathlib import Path

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ClientError


class Config(BaseConfig):
    DIST_NAME = "wpengine-cli"
    CREDENTIAL_TYPES = [CredentialType.USERNAME_PASSWORD]
    DEFAULT_BASE_URL = "https://api.wpengineapi.com/v1"
    AUTH_SETUP_INSTRUCTIONS = (
        "Before logging in:\n"
        "  1. Enable API access in the WP Engine User Portal.\n"
        "  2. Generate API credentials from the API Access page.\n"
        "  3. Enter the API User ID as USERNAME and the API Password as PASSWORD."
    )

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def storage_dir(self) -> Path:
        """Profile-aware storage directory for runtime state."""
        return self.get_profile_data_dir()

    def test_connection(self) -> dict:
        """Validate saved credentials with a live API call."""
        from .client import WpengineClient

        try:
            WpengineClient(config=self).list_accounts(limit=1)
            return {"api_test": "passed"}
        except ClientError as exc:
            return {"api_test": f"failed: {exc}"}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
