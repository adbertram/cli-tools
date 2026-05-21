"""Configuration management for {{Name}} CLI."""
from pathlib import Path
from cli_tools_shared.config import BaseConfig
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    CREDENTIAL_TYPES = [{{credential_types}}]
    DEFAULT_BASE_URL = "{{base_url}}"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=Path(__file__).resolve().parent.parent,
            profile=profile,
        )

    # Uncomment for dual-auth CLIs (API + browser_session):
    # def has_api_credentials(self) -> bool:
    #     """Check if API credentials are configured (ignores browser session)."""
    #     return bool(self.api_key)


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
