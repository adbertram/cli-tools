"""Configuration management for ShopGoodwill CLI."""
import time
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """ShopGoodwill CLI configuration."""

    DIST_NAME = "shopgoodwill-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS = ["SHOPGOODWILL_USERNAME", "SHOPGOODWILL_PASSWORD"]
    CUSTOM_ALL_FIELDS = [
        "SHOPGOODWILL_USERNAME",
        "SHOPGOODWILL_PASSWORD",
        "SHOPGOODWILL_ACCESS_TOKEN",
        "SHOPGOODWILL_REFRESH_TOKEN",
        "SHOPGOODWILL_TOKEN_EXPIRES_AT",
    ]
    CUSTOM_LOGIN_PROMPTS = [
        ("SHOPGOODWILL_USERNAME", "ShopGoodwill username/email", False),
        ("SHOPGOODWILL_PASSWORD", "ShopGoodwill password", True),
    ]
    CUSTOM_EPHEMERAL_FIELDS = [
        "SHOPGOODWILL_ACCESS_TOKEN",
        "SHOPGOODWILL_REFRESH_TOKEN",
        "SHOPGOODWILL_TOKEN_EXPIRES_AT",
    ]
    CUSTOM_SENSITIVE_FIELDS = [
        "SHOPGOODWILL_PASSWORD",
        "SHOPGOODWILL_ACCESS_TOKEN",
        "SHOPGOODWILL_REFRESH_TOKEN",
    ]

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def username(self) -> Optional[str]:
        """Get ShopGoodwill username."""
        return self._get("SHOPGOODWILL_USERNAME")

    @property
    def password(self) -> Optional[str]:
        """Get ShopGoodwill password."""
        return self._get("SHOPGOODWILL_PASSWORD")

    @property
    def access_token(self) -> Optional[str]:
        """Get access token."""
        return self._get("SHOPGOODWILL_ACCESS_TOKEN")

    @property
    def refresh_token(self) -> Optional[str]:
        """Get refresh token."""
        return self._get("SHOPGOODWILL_REFRESH_TOKEN")

    @property
    def token_expires_at(self) -> Optional[str]:
        """Get token expiration timestamp."""
        return self._get("SHOPGOODWILL_TOKEN_EXPIRES_AT")

    def has_valid_token(self) -> bool:
        """Check if we have a valid access token."""
        if not self.access_token:
            return False
        if not self.token_expires_at:
            return True
        try:
            return time.time() < float(self.token_expires_at)
        except ValueError:
            return False

    def save_credentials(self, username: str, password: str):
        """Save username and password to the active profile."""
        self._set("SHOPGOODWILL_USERNAME", username)
        self._set("SHOPGOODWILL_PASSWORD", password)

    def save_access_token(self, access_token: str):
        """Save access token to the active profile."""
        self._set("SHOPGOODWILL_ACCESS_TOKEN", access_token)

    def save_tokens(self, access_token: str, refresh_token: str, expires_at: str):
        """Save OAuth tokens to the active profile."""
        self._set("SHOPGOODWILL_ACCESS_TOKEN", access_token)
        self._set("SHOPGOODWILL_REFRESH_TOKEN", refresh_token)
        self._set("SHOPGOODWILL_TOKEN_EXPIRES_AT", expires_at)

    def test_connection(self) -> Optional[dict]:
        """Verify ShopGoodwill credentials with a lightweight auth check."""
        from .client import ClientError, ShopGoodwillClient

        try:
            if self.access_token and ShopGoodwillClient(require_auth=False, config=self).validate_token(self.access_token):
                return {"api_test": "passed", "token_valid": True}

            result = ShopGoodwillClient(require_auth=False, config=self).login(self.username, self.password)
            access_token = result.get("accessToken")
            if not access_token:
                return {"api_test": "failed: no access token returned"}
            self.save_access_token(access_token)
            return {"api_test": "passed", "token_valid": True}
        except ClientError as e:
            return {"api_test": f"failed: {e}"}


_configs: dict = {}


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create a config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
