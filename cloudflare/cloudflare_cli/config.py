"""Configuration management for Cloudflare CLI."""
from pathlib import Path
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):

    DIST_NAME = "cloudflare"
    CREDENTIAL_TYPES = [CredentialType.API_KEY]
    DEFAULT_BASE_URL = "https://api.cloudflare.com/client/v4"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
