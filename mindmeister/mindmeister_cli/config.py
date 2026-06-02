"""Configuration management for MindMeister CLI."""
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """MindMeister CLI configuration (personal access token auth)."""

    DIST_NAME = "mindmeister-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DEFAULT_BASE_URL = "https://www.mindmeister.com/services/rest/oauth2"
    CUSTOM_REQUIRED_FIELDS = ["MINDMEISTER_ACCESS_TOKEN"]
    CUSTOM_ALL_FIELDS = [
        "MINDMEISTER_API_KEY",
        "MINDMEISTER_CLIENT_ID",
        "MINDMEISTER_CLIENT_SECRET",
        "MINDMEISTER_ACCESS_TOKEN",
        "MINDMEISTER_REFRESH_TOKEN",
        "MINDMEISTER_TOKEN_EXPIRES_AT",
        "MINDMEISTER_BASE_URL",
    ]
    CUSTOM_LOGIN_PROMPTS = [
        ("MINDMEISTER_ACCESS_TOKEN", "MindMeister Personal Access Token", True),
    ]
    CUSTOM_EPHEMERAL_FIELDS = [
        "MINDMEISTER_REFRESH_TOKEN",
        "MINDMEISTER_TOKEN_EXPIRES_AT",
    ]
    CUSTOM_SENSITIVE_FIELDS = [
        "MINDMEISTER_API_KEY",
        "MINDMEISTER_CLIENT_SECRET",
        "MINDMEISTER_ACCESS_TOKEN",
        "MINDMEISTER_REFRESH_TOKEN",
    ]

    LOGIN_INSTRUCTIONS = (
        "To get your MindMeister Personal Access Token:\n"
        "  1. Go to https://www.mindmeister.com/api\n"
        "  2. Create or copy a token\n"
        "  3. Paste the token below"
    )

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def api_key(self) -> Optional[str]:
        return self._get("MINDMEISTER_API_KEY")

    @property
    def client_id(self) -> Optional[str]:
        return self._get("MINDMEISTER_CLIENT_ID")

    @property
    def client_secret(self) -> Optional[str]:
        return self._get("MINDMEISTER_CLIENT_SECRET")

    @property
    def access_token(self) -> Optional[str]:
        return self._get("MINDMEISTER_ACCESS_TOKEN")

    @property
    def refresh_token(self) -> Optional[str]:
        return self._get("MINDMEISTER_REFRESH_TOKEN")

    @property
    def token_expires_at(self) -> Optional[str]:
        return self._get("MINDMEISTER_TOKEN_EXPIRES_AT")

    @property
    def base_url(self) -> str:
        return self._get("MINDMEISTER_BASE_URL") or self.DEFAULT_BASE_URL

    def has_credentials(self) -> bool:
        """MindMeister accepts a PAT in access_token or a legacy API key."""
        return bool(self.access_token or self.api_key)

    def get_missing_credentials(self) -> list[str]:
        if self.has_credentials():
            return []
        return ["MINDMEISTER_ACCESS_TOKEN or MINDMEISTER_API_KEY"]

    def test_connection(self) -> Optional[dict]:
        """Verify credentials with a lightweight map-list call."""
        from .client import MindmeisterClient
        client = MindmeisterClient(config=self)
        if client.check_auth():
            return {"api_test": "passed"}
        return {"api_test": "failed: token rejected"}


_configs: dict = {}


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create a config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
