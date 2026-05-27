"""Configuration management for Twelvelabs CLI."""
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """TwelveLabs CLI configuration (API key auth)."""

    DIST_NAME = "twelvelabs-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DEFAULT_BASE_URL = "https://api.twelvelabs.io/v1.3"
    CUSTOM_REQUIRED_FIELDS = ["TWELVELABS_API_KEY"]
    CUSTOM_LOGIN_PROMPTS = [("TWELVELABS_API_KEY", "TwelveLabs API key", True)]
    CUSTOM_SENSITIVE_FIELDS = ["TWELVELABS_API_KEY"]

    LOGIN_INSTRUCTIONS = (
        "To get your TwelveLabs API key:\n"
        "  1. Go to https://playground.twelvelabs.io/dashboard/api-key\n"
        "  2. Create or copy your API key\n"
        "  3. Paste the key when prompted"
    )

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def api_key(self) -> Optional[str]:
        return self._get("TWELVELABS_API_KEY")

    @property
    def base_url(self) -> str:
        return self._get("TWELVELABS_BASE_URL") or self.DEFAULT_BASE_URL

    def test_connection(self) -> Optional[dict]:
        """Verify the API key with a lightweight indexes list call."""
        try:
            import requests
            response = requests.get(
                f"{self.base_url}/indexes",
                headers={"x-api-key": self.api_key},
                params={"page": 1},
                timeout=30,
            )
            if response.status_code >= 400:
                return {"api_test": f"failed: HTTP {response.status_code}: {response.text}"}
            return {"api_test": "passed"}
        except Exception as e:
            return {"api_test": f"failed: {e}"}


_configs: dict = {}


def get_config(profile=None) -> Config:
    """Get or create a config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
