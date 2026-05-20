"""Configuration management for Snagit CLI."""
import os
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from dotenv import set_key


class Config(BaseConfig):
    """Configuration manager for Snagit CLI authentication and settings."""

    CREDENTIAL_TYPES: list = []  # custom field set; managed by this subclass
    DIST_NAME = "snagit-cli"

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def api_key(self) -> Optional[str]:
        """Get Snagit API key."""
        return os.getenv("SNAGIT_API_KEY")

    @property
    def client_id(self) -> Optional[str]:
        """Get Snagit OAuth client ID."""
        return os.getenv("SNAGIT_CLIENT_ID")

    @property
    def client_secret(self) -> Optional[str]:
        """Get Snagit OAuth client secret."""
        return os.getenv("SNAGIT_CLIENT_SECRET")

    @property
    def access_token(self) -> Optional[str]:
        """Get Snagit access token."""
        return os.getenv("SNAGIT_ACCESS_TOKEN")

    @property
    def refresh_token(self) -> Optional[str]:
        """Get Snagit refresh token."""
        return os.getenv("SNAGIT_REFRESH_TOKEN")

    @property
    def token_expires_at(self) -> Optional[str]:
        """Get token expiration timestamp."""
        return os.getenv("SNAGIT_TOKEN_EXPIRES_AT")

    @property
    def base_url(self) -> str:
        """Get Snagit API base URL."""
        default_path = Path.home() / "Pictures" / "Snagit" / "Autosaved Captures.localized"
        return os.getenv("SNAGIT_BASE_URL", default_path.as_uri() + "/")

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
        """Save OAuth tokens to .env file."""
        set_key(str(self.env_file_path), "SNAGIT_ACCESS_TOKEN", access_token)
        set_key(str(self.env_file_path), "SNAGIT_REFRESH_TOKEN", refresh_token)
        set_key(str(self.env_file_path), "SNAGIT_TOKEN_EXPIRES_AT", expires_at)

    def save_api_key(self, api_key: str):
        """Save API key to .env file."""
        set_key(str(self.env_file_path), "SNAGIT_API_KEY", api_key)

    def clear_credentials(self):
        """Clear all credentials from .env file."""
        set_key(str(self.env_file_path), "SNAGIT_API_KEY", "")
        set_key(str(self.env_file_path), "SNAGIT_ACCESS_TOKEN", "")
        set_key(str(self.env_file_path), "SNAGIT_REFRESH_TOKEN", "")
        set_key(str(self.env_file_path), "SNAGIT_TOKEN_EXPIRES_AT", "")


# Global config instance - singleton pattern
_config: Optional[Config] = None


def get_config() -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config
