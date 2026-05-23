"""Configuration management for Snagit CLI."""
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration manager for Snagit CLI authentication and settings."""

    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS = []
    CUSTOM_ALL_FIELDS = [
        "SNAGIT_API_KEY",
        "SNAGIT_CLIENT_ID",
        "SNAGIT_CLIENT_SECRET",
        "SNAGIT_ACCESS_TOKEN",
        "SNAGIT_REFRESH_TOKEN",
        "SNAGIT_TOKEN_EXPIRES_AT",
        "SNAGIT_BASE_URL",
    ]
    CUSTOM_LOGIN_PROMPTS = []
    CUSTOM_EPHEMERAL_FIELDS = [
        "SNAGIT_ACCESS_TOKEN",
        "SNAGIT_REFRESH_TOKEN",
        "SNAGIT_TOKEN_EXPIRES_AT",
    ]
    CUSTOM_SENSITIVE_FIELDS = [
        "SNAGIT_API_KEY",
        "SNAGIT_CLIENT_SECRET",
        "SNAGIT_ACCESS_TOKEN",
        "SNAGIT_REFRESH_TOKEN",
    ]
    DIST_NAME = "snagit-cli"

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def api_key(self) -> Optional[str]:
        """Get Snagit API key."""
        return self._get("SNAGIT_API_KEY")

    @property
    def client_id(self) -> Optional[str]:
        """Get Snagit OAuth client ID."""
        return self._get("SNAGIT_CLIENT_ID")

    @property
    def client_secret(self) -> Optional[str]:
        """Get Snagit OAuth client secret."""
        return self._get("SNAGIT_CLIENT_SECRET")

    @property
    def access_token(self) -> Optional[str]:
        """Get Snagit access token."""
        return self._get("SNAGIT_ACCESS_TOKEN")

    @property
    def refresh_token(self) -> Optional[str]:
        """Get Snagit refresh token."""
        return self._get("SNAGIT_REFRESH_TOKEN")

    @property
    def token_expires_at(self) -> Optional[str]:
        """Get token expiration timestamp."""
        return self._get("SNAGIT_TOKEN_EXPIRES_AT")

    @property
    def base_url(self) -> str:
        """Get Snagit API base URL."""
        default_path = Path.home() / "Pictures" / "Snagit" / "Autosaved Captures.localized"
        return self._get("SNAGIT_BASE_URL") or default_path.as_uri() + "/"

    def has_credentials(self) -> bool:
        """Check if required credentials are available."""
        # Modify this based on your auth type (API key vs OAuth)
        return bool(self.api_key or self.access_token)

    def get_missing_credentials(self) -> list[str]:
        """Get list of missing credentials."""
        missing = []
        # Modify based on required credentials
        if not self.api_key and not self.access_token:
            missing.append("SNAGIT_API_KEY or SNAGIT_ACCESS_TOKEN")
        return missing

    def save_tokens(self, access_token: str, refresh_token: str, expires_at: str):
        """Save OAuth tokens through the central CLI-tools secret manager."""
        self._set("SNAGIT_ACCESS_TOKEN", access_token)
        self._set("SNAGIT_REFRESH_TOKEN", refresh_token)
        self._set("SNAGIT_TOKEN_EXPIRES_AT", expires_at)

    def save_api_key(self, api_key: str):
        """Save API key through the central CLI-tools secret manager."""
        self._set("SNAGIT_API_KEY", api_key)

    def clear_credentials(self):
        """Clear all credentials from the profile and central secret manager."""
        self._clear("SNAGIT_API_KEY")
        self._clear("SNAGIT_ACCESS_TOKEN")
        self._clear("SNAGIT_REFRESH_TOKEN")
        self._clear("SNAGIT_TOKEN_EXPIRES_AT")


# Global config instance - singleton pattern
_config: Optional[Config] = None


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None or profile is not None:
        _config = Config(profile=profile)
    return _config
