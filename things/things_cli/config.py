"""Configuration management for Things CLI."""
import os
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from dotenv import set_key


class Config(BaseConfig):
    """Configuration manager for Things CLI authentication and settings.

    Inherits per-account env-file resolution and migration from BaseConfig:
    credentials live at ``~/.local/share/cli-tools/things/authentication_profiles/<profile>/.env``,
    not in the source repo.
    """

    CREDENTIAL_TYPES: list = []  # custom field set; managed by this subclass
    DIST_NAME = "things-cli"

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def api_key(self) -> Optional[str]:
        """Get Things API key."""
        return os.getenv("THINGS_API_KEY")

    @property
    def client_id(self) -> Optional[str]:
        """Get Things OAuth client ID."""
        return os.getenv("THINGS_CLIENT_ID")

    @property
    def client_secret(self) -> Optional[str]:
        """Get Things OAuth client secret."""
        return os.getenv("THINGS_CLIENT_SECRET")

    @property
    def access_token(self) -> Optional[str]:
        """Get Things access token."""
        return os.getenv("THINGS_ACCESS_TOKEN")

    @property
    def refresh_token(self) -> Optional[str]:
        """Get Things refresh token."""
        return os.getenv("THINGS_REFRESH_TOKEN")

    @property
    def token_expires_at(self) -> Optional[str]:
        """Get token expiration timestamp."""
        return os.getenv("THINGS_TOKEN_EXPIRES_AT")

    @property
    def base_url(self) -> str:
        """Get Things API base URL."""
        return os.getenv("THINGS_BASE_URL", "sqlite://local")

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
        """Save OAuth tokens to .env file and update environment."""
        set_key(str(self.env_file_path), "THINGS_ACCESS_TOKEN", access_token)
        set_key(str(self.env_file_path), "THINGS_REFRESH_TOKEN", refresh_token)
        set_key(str(self.env_file_path), "THINGS_TOKEN_EXPIRES_AT", expires_at)
        os.environ["THINGS_ACCESS_TOKEN"] = access_token
        os.environ["THINGS_REFRESH_TOKEN"] = refresh_token
        os.environ["THINGS_TOKEN_EXPIRES_AT"] = expires_at

    def save_api_key(self, api_key: str):
        """Save API key to .env file and update environment."""
        set_key(str(self.env_file_path), "THINGS_API_KEY", api_key)
        os.environ["THINGS_API_KEY"] = api_key

    def clear_credentials(self):
        """Clear all credentials from .env file and environment."""
        for field in (
            "THINGS_API_KEY",
            "THINGS_ACCESS_TOKEN",
            "THINGS_REFRESH_TOKEN",
            "THINGS_TOKEN_EXPIRES_AT",
        ):
            set_key(str(self.env_file_path), field, "")
            os.environ.pop(field, None)


# Global config instance - singleton pattern
_config: Optional[Config] = None


def get_config() -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config
