"""Configuration management for Buttondown CLI."""
from pathlib import Path
import requests

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):

    DIST_NAME = "buttondown-cli"
    CREDENTIAL_TYPES = [CredentialType.API_KEY]
    DEFAULT_BASE_URL = "https://api.buttondown.com/v1"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    # Uncomment for dual-auth CLIs (API + browser_session):
    # def has_api_credentials(self) -> bool:
    #     """Check if API credentials are configured (ignores browser session)."""
    #     return bool(self.api_key)

    def test_connection(self):
        """Verify the saved API key against Buttondown."""
        response = requests.get(
            f"{self.base_url.rstrip('/')}/ping",
            headers={"Authorization": f"Token {self.api_key}", "Accept": "application/json"},
            timeout=15,
        )
        if 200 <= response.status_code < 300:
            return {"api_test": "passed"}
        return {"api_test": f"failed: HTTP {response.status_code}"}


_configs = {}
_global_profile = None


def get_config(profile=None):
    effective_profile = profile if profile is not None else _global_profile
    key = effective_profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=effective_profile)
    return _configs[key]


def set_global_profile(profile=None):
    global _global_profile
    _global_profile = profile
