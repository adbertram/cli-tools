"""Configuration management for the 10Web CLI."""

import requests

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    DIST_NAME = "tenweb-cli"
    CREDENTIAL_TYPES = [CredentialType.API_KEY]
    DEFAULT_BASE_URL = "https://api.10web.io"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def test_connection(self) -> dict:
        """Test the configured API key with a lightweight account request."""
        try:
            response = requests.get(
                f"{self.base_url}/v1/account/websites",
                headers={"x-api-key": self.api_key, "Accept": "application/json"},
                timeout=30,
            )
            if response.ok:
                return {"api_test": "passed"}
            return {"api_test": f"failed: {response.status_code} {response.text}"}
        except Exception as exc:
            return {"api_test": f"failed: {exc}"}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
