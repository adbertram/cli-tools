"""Configuration management for Descript CLI."""
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Descript CLI configuration."""

    DIST_NAME = "descript-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DEFAULT_BASE_URL = "https://descriptapi.com/v1"
    CUSTOM_REQUIRED_FIELDS: list = []
    CUSTOM_ALL_FIELDS = ["DESCRIPT_BASE_URL"]

    LOGIN_INSTRUCTIONS = (
        "Descript API authentication is managed by the official descript-api CLI.\n"
        "The descript wrapper auto-provisions @descript/platform-cli@latest, "
        "then runs 'descript auth login' or 'descript config set api-key'."
    )

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def base_url(self) -> str:
        return self._get("DESCRIPT_BASE_URL") or self.DEFAULT_BASE_URL

    def get_missing_credentials(self) -> list[str]:
        return []

    def test_connection(self) -> Optional[dict]:
        """Verify the official Descript API CLI is configured."""
        from .platform import official_config_validate

        return official_config_validate()


_configs: dict = {}


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create a config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
