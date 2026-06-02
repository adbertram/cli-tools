"""Configuration management for Msword CLI."""
from pathlib import Path
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    DIST_NAME = "msword-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS = []
    CUSTOM_ALL_FIELDS = []
    CUSTOM_EPHEMERAL_FIELDS = []

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def test_connection(self) -> dict:
        """Local file processing requires no remote authentication."""
        return {"api_test": "passed"}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
