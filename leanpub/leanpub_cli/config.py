"""Configuration management for Leanpub CLI."""
from pathlib import Path
from typing import List

import requests

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ConfigError


class Config(BaseConfig):

    DIST_NAME = "leanpub-cli"
    CREDENTIAL_TYPES = [CredentialType.API_KEY]
    DEFAULT_BASE_URL = "https://leanpub.com"
    LOGIN_INSTRUCTIONS = (
        "Leanpub API access requires a Pro plan. Generate an API key at "
        "https://leanpub.com/author_dashboard/api_key."
    )

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def book_slugs(self) -> List[str]:
        """Configured Leanpub book slugs for author-level stats."""
        configured = self._get("BOOK_SLUGS")
        if configured is None:
            return []

        slugs = [slug.strip() for slug in configured.split(",")]
        if not slugs or any(not slug for slug in slugs):
            raise ConfigError("BOOK_SLUGS must be a comma-separated list of non-empty slugs.")
        return slugs

    def test_connection(self) -> dict:
        """Verify the configured API key with Leanpub."""
        response = requests.get(
            f"{self.base_url}/current_user.json",
            params={"api_key": self.api_key},
            timeout=30,
        )
        if not response.ok:
            return {"api_test": f"failed: HTTP {response.status_code}"}

        data = response.json()
        return {
            "api_test": "passed",
            "username": data["username"],
            "email": data["email"],
        }


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
