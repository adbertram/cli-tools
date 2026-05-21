"""Configuration management for Awin CLI."""
from pathlib import Path

import requests

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    DIST_NAME = "awin-cli"
    CREDENTIAL_TYPES = [CredentialType.PERSONAL_ACCESS_TOKEN]
    DEFAULT_BASE_URL = "https://api.awin.com"
    AUTH_EXTRA_PROMPTS = [
        ("AWIN_PUBLISHER_ID", "Awin Publisher ID (numeric, from https://ui.awin.com)", False),
    ]
    LOGIN_INSTRUCTIONS = (
        "Awin requires two values:\n"
        "1. Personal access token (Bearer) generated at\n"
        "   https://ui.awin.com/awin-api\n"
        "2. Your Awin Publisher ID (numeric), shown in the\n"
        "   Awin UI under your account name."
    )

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def awin_publisher_id(self) -> str:
        value = self._get("AWIN_PUBLISHER_ID")
        if not value:
            raise ValueError(
                "AWIN_PUBLISHER_ID is not configured. Run 'awin auth login'."
            )
        return value

    def test_connection(self) -> dict:
        if not self.has_credentials():
            missing = ", ".join(self.get_missing_credentials())
            return {"api_test": f"failed: missing {missing}"}

        response = requests.get(
            f"{self.base_url.rstrip('/')}/accounts",
            headers={
                "Authorization": f"Bearer {self.personal_access_token}",
                "Accept": "application/json",
            },
            timeout=30,
        )
        if response.ok:
            return {"api_test": "passed"}
        return {"api_test": f"failed: HTTP {response.status_code}: {response.text[:500]}"}

    @property
    def storage_dir(self) -> Path:
        return self.get_profile_data_dir()


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
