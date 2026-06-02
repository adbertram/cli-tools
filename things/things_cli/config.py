"""Configuration management for Things CLI."""
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration manager for Things CLI authentication and settings.

    Sensitive credentials are stored in the central CLI-tools secret manager.
    Profile files only keep ``secret://...`` references under
    ``~/.local/share/cli-tools/things/authentication_profiles/<profile>/``.
    """

    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS = []
    CUSTOM_ALL_FIELDS = [
        "THINGS_API_KEY",
        "THINGS_CLIENT_ID",
        "THINGS_CLIENT_SECRET",
        "THINGS_ACCESS_TOKEN",
        "THINGS_REFRESH_TOKEN",
        "THINGS_TOKEN_EXPIRES_AT",
        "THINGS_BASE_URL",
    ]
    CUSTOM_LOGIN_PROMPTS = []
    CUSTOM_EPHEMERAL_FIELDS = [
        "THINGS_ACCESS_TOKEN",
        "THINGS_REFRESH_TOKEN",
        "THINGS_TOKEN_EXPIRES_AT",
    ]
    CUSTOM_SENSITIVE_FIELDS = [
        "THINGS_API_KEY",
        "THINGS_CLIENT_SECRET",
        "THINGS_ACCESS_TOKEN",
        "THINGS_REFRESH_TOKEN",
    ]
    DIST_NAME = "things-cli"

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def api_key(self) -> Optional[str]:
        """Get Things API key."""
        return self._get("THINGS_API_KEY")

    @property
    def client_id(self) -> Optional[str]:
        """Get Things OAuth client ID."""
        return self._get("THINGS_CLIENT_ID")

    @property
    def client_secret(self) -> Optional[str]:
        """Get Things OAuth client secret."""
        return self._get("THINGS_CLIENT_SECRET")

    @property
    def access_token(self) -> Optional[str]:
        """Get Things access token."""
        return self._get("THINGS_ACCESS_TOKEN")

    @property
    def refresh_token(self) -> Optional[str]:
        """Get Things refresh token."""
        return self._get("THINGS_REFRESH_TOKEN")

    @property
    def token_expires_at(self) -> Optional[str]:
        """Get token expiration timestamp."""
        return self._get("THINGS_TOKEN_EXPIRES_AT")

    @property
    def base_url(self) -> str:
        """Get Things API base URL."""
        return self._get("THINGS_BASE_URL") or "sqlite://local"

    def has_credentials(self) -> bool:
        """Check if required credentials are available."""
        return bool(self.api_key or self.access_token)

    def get_missing_credentials(self) -> list[str]:
        """Get list of missing credentials."""
        missing = []
        if not self.api_key and not self.access_token:
            missing.append("THINGS_API_KEY or THINGS_ACCESS_TOKEN")
        return missing

    def save_tokens(self, access_token: str, refresh_token: str, expires_at: str):
        """Save OAuth tokens through the central CLI-tools secret manager."""
        self._set("THINGS_ACCESS_TOKEN", access_token)
        self._set("THINGS_REFRESH_TOKEN", refresh_token)
        self._set("THINGS_TOKEN_EXPIRES_AT", expires_at)

    def save_api_key(self, api_key: str):
        """Save API key through the central CLI-tools secret manager."""
        self._set("THINGS_API_KEY", api_key)

    def clear_credentials(self):
        """Clear all credentials from the profile and central secret manager."""
        for field in (
            "THINGS_API_KEY",
            "THINGS_ACCESS_TOKEN",
            "THINGS_REFRESH_TOKEN",
            "THINGS_TOKEN_EXPIRES_AT",
        ):
            self._clear(field)


# Global config instance - singleton pattern
_config: Optional[Config] = None


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None or profile is not None:
        _config = Config(profile=profile)
    return _config
