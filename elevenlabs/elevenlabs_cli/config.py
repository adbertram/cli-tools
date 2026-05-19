"""Configuration management for Elevenlabs CLI."""
import requests
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.API_KEY]
    DEFAULT_BASE_URL = "https://api.elevenlabs.io"
    DIST_NAME = "elevenlabs-cli"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def test_connection(self):
        """Verify the configured API key against the subscription endpoint."""
        if not self.api_key:
            return {"api_test": "failed: missing API_KEY"}
        try:
            response = requests.get(
                f"{self.base_url.rstrip('/')}/v1/user/subscription",
                headers={"xi-api-key": self.api_key, "Accept": "application/json"},
                timeout=30,
            )
        except requests.exceptions.RequestException as exc:
            return {"api_test": f"failed: {exc}"}
        if not response.ok:
            return {"api_test": f"failed: HTTP {response.status_code}: {response.text[:500]}"}
        data = response.json()
        return {
            "api_test": "passed",
            "tier": data["tier"],
            "status": data["status"],
        }


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
