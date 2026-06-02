"""Configuration management for Pinterest CLI."""
from pathlib import Path
from typing import Optional

import requests

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Pinterest CLI configuration."""

    DIST_NAME = "pinterest-cli"
    CREDENTIAL_TYPES = [CredentialType.OAUTH_AUTHORIZATION_CODE]
    DEFAULT_BASE_URL = "https://api.pinterest.com/v5"
    OAUTH_AUTH_URL = "https://www.pinterest.com/oauth/"
    OAUTH_SCOPES = ["user_accounts:read", "boards:read", "pins:read"]
    OAUTH_REDIRECT_URI = "http://localhost/"
    OAUTH_TOKEN_AUTH = "basic"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def OAUTH_TOKEN_URL(self) -> str:
        """Pinterest token endpoint follows the configured API host."""
        return f"{self.base_url}/oauth/token"

    @property
    def storage_dir(self) -> Path:
        """Directory used by shared cache/profile helpers."""
        return self.get_profile_data_dir()

    @property
    def refresh_token_expires_at(self) -> Optional[str]:
        return self._get("REFRESH_TOKEN_EXPIRES_AT")

    def test_connection(self) -> dict:
        """Test API connectivity with a lightweight user-account request."""
        response = requests.get(
            f"{self.base_url}/user_account",
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        return {
            "api_test": "passed",
            "account_id": payload.get("id"),
            "username": payload.get("username"),
        }

_configs = {}


def get_config(profile=None):
    """Get or create a config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
