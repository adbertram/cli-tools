"""Configuration management for Manus CLI."""
from pathlib import Path

import requests

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    LEGACY_BASE_URL = "https://api.manus.ai/v1"

    DIST_NAME = "manus-cli"
    CREDENTIAL_TYPES = [CredentialType.API_KEY]
    DEFAULT_BASE_URL = "https://api.manus.ai"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )
        self._migrate_legacy_base_url()

    def _migrate_legacy_base_url(self) -> None:
        """Promote saved v1 BASE_URL values to the v2 API host root."""
        saved_base_url = self._get("BASE_URL")
        if saved_base_url and saved_base_url.rstrip("/") == self.LEGACY_BASE_URL:
            self._set("BASE_URL", self.DEFAULT_BASE_URL)

    @property
    def storage_dir(self) -> Path:
        """Profile-aware storage directory for cache/state helpers."""
        return self.get_profile_data_dir()

    def test_connection(self) -> dict:
        """Validate API-key authentication with a lightweight v2 list call."""
        try:
            response = requests.get(
                f"{self.base_url}/v2/task.list",
                headers={"x-manus-api-key": self.api_key},
                params={"limit": 1},
                timeout=10,
            )
            if response.ok:
                return {"api_test": "passed"}
            return {"api_test": f"failed: HTTP {response.status_code}"}
        except Exception as exc:
            return {"api_test": f"failed: {exc}"}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
