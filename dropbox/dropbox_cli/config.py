"""Configuration management for Dropbox CLI."""
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration manager for Dropbox CLI authentication and settings."""

    DIST_NAME = "dropbox-cli"

    CREDENTIAL_TYPES = [CredentialType.OAUTH]
    DEFAULT_BASE_URL = "https://api.dropboxapi.com"
    OAUTH_TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    # ==================== Dropbox-Specific Properties ====================

    @property
    def app_key(self) -> Optional[str]:
        """Get Dropbox app key (maps to CLIENT_ID)."""
        return self.client_id

    @property
    def app_secret(self) -> Optional[str]:
        """Get Dropbox app secret (maps to CLIENT_SECRET)."""
        return self.client_secret

    @property
    def account_id(self) -> Optional[str]:
        """Get Dropbox account ID."""
        return self._get("ACCOUNT_ID")

    def has_app_credentials(self) -> bool:
        """Check if app credentials are configured."""
        return bool(self.app_key)

    def save_app_credentials(self, app_key: str, app_secret: Optional[str] = None):
        """Save app credentials to .env file."""
        self._set("CLIENT_ID", app_key)
        if app_secret:
            self._set("CLIENT_SECRET", app_secret)

    def save_tokens(
        self,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_at: Optional[str] = None,
        account_id: Optional[str] = None,
    ):
        """Save OAuth tokens to .env file."""
        self._set("ACCESS_TOKEN", access_token)
        if refresh_token:
            self._set("REFRESH_TOKEN", refresh_token)
        if expires_at:
            self._set("TOKEN_EXPIRES_AT", expires_at)
        if account_id:
            self._set("ACCOUNT_ID", account_id)

    def test_connection(self) -> dict:
        """Test API connectivity by fetching account info."""
        try:
            from .client import DropboxClient
            client = DropboxClient(require_auth=True)
            account = client.get_account()
            return {
                "api_test": "passed",
                "name": account.get("name", "unknown"),
                "email": account.get("email", "unknown"),
            }
        except Exception as e:
            return {"api_test": f"failed: {e}"}


# Singleton cache keyed by profile name
_configs: dict[str, Config] = {}


def get_config(profile=None) -> Config:
    """Get or create config for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
