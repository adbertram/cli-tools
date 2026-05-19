"""Configuration management for Simpletexting CLI."""
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    DIST_NAME = "simpletexting-cli"
    CREDENTIAL_TYPES = [CredentialType.API_KEY]
    DEFAULT_BASE_URL = "https://app2.simpletexting.com/v1"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def test_connection(self) -> Optional[dict]:
        """Verify the API token against the documented credits endpoint."""
        import requests

        try:
            response = requests.get(
                f"{self.DEFAULT_BASE_URL}/messaging/check",
                params={"token": self.api_key},
                headers={"accept": "application/json"},
                timeout=10,
            )
        except Exception as exc:
            return {"api_test": f"failed: {exc}"}

        if not response.ok:
            return {"api_test": f"failed: HTTP {response.status_code}"}

        data = response.json()
        if data.get("code") == 1:
            return {
                "api_test": "passed",
                "message": data.get("message", ""),
            }
        return {"api_test": f"failed: {data.get('message', 'unknown API error')}"}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
