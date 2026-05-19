"""Configuration management for Databox CLI."""
from typing import Optional

import requests

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    DIST_NAME = "databox-cli"
    CREDENTIAL_TYPES = [CredentialType.API_KEY]
    DEFAULT_BASE_URL = "https://api.databox.com"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def test_connection(self) -> Optional[dict]:
        """Test API connection by validating the configured API key."""
        if not self.api_key:
            return {"api_test": "failed: API key not configured"}
        try:
            response = requests.get(
                f"{self.base_url}/v1/auth/validate-key",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10,
            )
            if response.ok:
                return {"api_test": "passed", "base_url": self.base_url}
            return {"api_test": f"failed: HTTP {response.status_code}"}
        except requests.exceptions.RequestException as exc:
            return {"api_test": f"failed: {exc}"}

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
