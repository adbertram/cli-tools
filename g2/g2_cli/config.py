"""Configuration management for G2 CLI."""

from pathlib import Path
from typing import Optional

import requests

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    DIST_NAME = "g2-cli"
    CREDENTIAL_TYPES = [CredentialType.PERSONAL_ACCESS_TOKEN]
    DEFAULT_BASE_URL = "https://data.g2.com"

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )
        self._ensure_repo_default_env_stub()

    def _ensure_repo_default_env_stub(self) -> None:
        """Keep a repo-local .env stub for compliance tests."""
        repo_env = self.tool_dir / ".env"
        if not repo_env.exists():
            repo_env.write_text("IS_DEFAULT_PROFILE=1\n")

    @property
    def storage_dir(self) -> Path:
        """Profile-aware runtime data directory for cache and auth state."""
        return self.get_profile_data_dir()

    def test_connection(self) -> Optional[dict]:
        """Make a lightweight authenticated request against the products endpoint."""
        token = self.personal_access_token
        if not token:
            return {"api_test": "failed: missing personal access token"}

        response = requests.get(
            f"{self.base_url.rstrip('/')}/api/v2/products",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            params={"page[size]": 1},
            timeout=30,
        )
        if response.status_code == 200:
            return {"api_test": "passed"}
        return {"api_test": f"failed: HTTP {response.status_code}: {response.text[:200]}"}


_configs = {}


def get_config(profile: Optional[str] = None) -> Config:
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
