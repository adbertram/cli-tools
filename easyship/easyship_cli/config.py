"""Configuration management for Easyship CLI."""
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.PERSONAL_ACCESS_TOKEN]
    DEFAULT_BASE_URL = "https://public-api.easyship.com/2024-09"
    DIST_NAME = "easyship-cli"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def test_connection(self) -> Optional[dict]:
        """Make a lightweight authenticated request to the account endpoint."""
        import requests

        token = self.personal_access_token
        if not token:
            return {"api_test": "failed: missing personal access token"}

        response = requests.get(
            f"{self.base_url.rstrip('/')}/account",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
            timeout=30,
        )
        if response.status_code == 200:
            return {"api_test": "passed"}
        return {"api_test": f"failed: HTTP {response.status_code}"}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
