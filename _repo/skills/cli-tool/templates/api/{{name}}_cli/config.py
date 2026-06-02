"""Configuration management for {{Name}} CLI."""

from pathlib import Path

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ClientError


class Config(BaseConfig):
    DIST_NAME = "{{name}}-cli"
    CREDENTIAL_TYPES = [{{credential_types}}]
    DEFAULT_BASE_URL = "{{base_url}}"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def storage_dir(self) -> Path:
        """Profile-aware storage directory for runtime state."""
        return self.get_profile_data_dir()

    # Uncomment for dual-auth CLIs (API + browser_session):
    # def has_api_credentials(self) -> bool:
    #     """Check if API credentials are configured (ignores browser session)."""
    #     return bool(self.api_key)

    def test_connection(self) -> dict:
        """Validate saved credentials with a live API call."""
        from .client import {{Name}}Client

        try:
            {{Name}}Client(config=self).list_items(limit=1)
            return {"api_test": "passed"}
        except ClientError as exc:
            return {"api_test": f"failed: {exc}"}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
