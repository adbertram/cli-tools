"""Configuration management for Scrunch CLI."""
from pathlib import Path
import requests
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):

    DIST_NAME = "scrunch-cli"
    CREDENTIAL_TYPES = [CredentialType.API_KEY]
    DEFAULT_BASE_URL = "https://api.scrunchai.com/v1"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def test_connection(self) -> bool:
        """Test API connection with a lightweight request."""
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        response = requests.get(f"{self.base_url}/brands", headers=headers, timeout=10)
        response.raise_for_status()
        return True


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
