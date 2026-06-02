"""Configuration management for Hyvor CLI."""
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for Hyvor CLI extending BaseConfig."""

    DIST_NAME = "hyvor-cli"

    CREDENTIAL_TYPES = [CredentialType.API_KEY]
    DEFAULT_BASE_URL = "https://talk.hyvor.com/api/console/v1"
    AUTH_EXTRA_PROMPTS = [
        ("WEBSITE_ID", "Hyvor Website ID", False),
    ]

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def website_id(self) -> Optional[int]:
        """Get Hyvor website ID."""
        val = self._get("WEBSITE_ID")
        if val:
            try:
                return int(val)
            except ValueError:
                return None
        return None

    def has_credentials(self) -> bool:
        """Check if required credentials (API key + website ID) are available."""
        return bool(super().has_credentials() and self.website_id)

    def get_missing_credentials(self) -> list:
        """Get list of missing credentials."""
        missing = super().get_missing_credentials()
        if not self.website_id:
            missing.append("WEBSITE_ID")
        return missing

    def test_connection(self) -> Optional[dict]:
        """Test API connection with a lightweight call."""
        import requests
        try:
            response = requests.get(
                f"{self.base_url}/{self.website_id}/comments",
                headers={
                    "X-API-KEY": self.api_key,
                    "Accept": "application/json",
                },
                params={"limit": 1},
                timeout=10,
            )
            if response.ok:
                return {"api_test": "passed", "website_id": self.website_id}
            return {"api_test": f"failed: HTTP {response.status_code}"}
        except requests.exceptions.RequestException as e:
            return {"api_test": f"failed: {e}"}


def get_config(profile=None) -> Config:
    """Get or create a Config instance."""
    return Config(profile=profile)
