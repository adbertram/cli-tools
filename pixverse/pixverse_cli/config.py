"""Configuration management for PixVerse CLI."""
import requests

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    DIST_NAME = "pixverse-cli"
    CREDENTIAL_TYPES = [CredentialType.API_KEY]
    DEFAULT_BASE_URL = "https://app-api.pixverse.ai/openapi/v2"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def test_connection(self) -> dict:
        """Test PixVerse auth using the documented balance endpoint."""
        try:
            response = requests.get(
                f"{self.base_url}/account/balance",
                headers={"API-KEY": self.api_key},
                timeout=30,
            )
            if response.ok:
                return {"api_test": "passed"}
            return {"api_test": f"failed: {response.status_code} {response.text}"}
        except Exception as e:
            return {"api_test": f"failed: {e}"}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
