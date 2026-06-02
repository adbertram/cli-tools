"""Configuration management for PartnerStack CLI."""
import requests

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    DIST_NAME = "partnerstack-cli"
    CREDENTIAL_TYPES = [CredentialType.API_KEY, CredentialType.CUSTOM]
    DEFAULT_BASE_URL = "https://api.partnerstack.com/api/v2"
    LOGIN_INSTRUCTIONS = (
        "Configure API_KEY for Bearer-auth Partner API commands. "
        "Use 'partnerstack auth login-basic' for form-templates and applications."
    )

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def test_connection(self):
        """Validate the saved API key against PartnerStack."""
        if not self.api_key:
            return {"api_test": "failed: missing API_KEY"}

        response = requests.get(
            f"{self.base_url.rstrip('/')}/rewards",
            headers={"Accept": "application/json", "Authorization": f"Bearer {self.api_key}"},
            params={"limit": 1},
            timeout=30,
        )
        if response.ok:
            return {"api_test": "passed"}

        body = response.json()
        message = body["message"]
        return {"api_test": f"failed: HTTP {response.status_code}: {message}"}

    def clear_credentials(self):
        """Clear both Bearer and Basic auth credentials from the active profile."""
        super().clear_credentials()
        self._clear("USERNAME")
        self._clear("PASSWORD")

    def save_basic_credentials(self, public_key: str, secret_key: str):
        """Save PartnerStack Basic auth credentials in the active profile."""
        self._set("USERNAME", public_key)
        self._set("PASSWORD", secret_key)


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
