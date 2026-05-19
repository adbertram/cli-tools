"""Configuration management for X CLI."""
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """X CLI configuration.

    X API v2 requires OAuth 1.0a for posting tweets. Four static credentials:
    consumer_key, consumer_secret, access_token, access_token_secret.

    A bearer token is optionally stored for app-only read operations but is
    not part of the required OAuth 1.0a credential set.
    """

    DIST_NAME = "x-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DEFAULT_BASE_URL = "https://api.twitter.com"
    CUSTOM_REQUIRED_FIELDS = [
        "X_CONSUMER_KEY",
        "X_CONSUMER_SECRET",
        "X_ACCESS_TOKEN",
        "X_ACCESS_TOKEN_SECRET",
    ]
    CUSTOM_ALL_FIELDS = [
        "X_CONSUMER_KEY",
        "X_CONSUMER_SECRET",
        "X_ACCESS_TOKEN",
        "X_ACCESS_TOKEN_SECRET",
        "X_BEARER_TOKEN",
        "X_BASE_URL",
    ]
    CUSTOM_LOGIN_PROMPTS = [
        ("X_CONSUMER_KEY", "Consumer Key (API Key)", False),
        ("X_CONSUMER_SECRET", "Consumer Secret (API Secret)", True),
        ("X_ACCESS_TOKEN", "Access Token", False),
        ("X_ACCESS_TOKEN_SECRET", "Access Token Secret", True),
    ]
    CUSTOM_SENSITIVE_FIELDS = [
        "X_CONSUMER_KEY",
        "X_CONSUMER_SECRET",
        "X_ACCESS_TOKEN",
        "X_ACCESS_TOKEN_SECRET",
        "X_BEARER_TOKEN",
    ]

    LOGIN_INSTRUCTIONS = (
        "To get your X API OAuth 1.0a credentials:\n"
        "  1. Go to https://developer.x.com/en/portal/dashboard\n"
        "  2. Create or open an app\n"
        "  3. Under 'Keys and tokens' generate:\n"
        "     - Consumer Key / Consumer Secret (API Key / Secret)\n"
        "     - Access Token / Access Token Secret (User authentication tokens)"
    )

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    # ---- Compatibility shims for existing client.py code ----

    @property
    def consumer_key(self) -> Optional[str]:
        return self._get("X_CONSUMER_KEY")

    @property
    def consumer_secret(self) -> Optional[str]:
        return self._get("X_CONSUMER_SECRET")

    @property
    def access_token(self) -> Optional[str]:
        return self._get("X_ACCESS_TOKEN")

    @property
    def access_token_secret(self) -> Optional[str]:
        return self._get("X_ACCESS_TOKEN_SECRET")

    @property
    def bearer_token(self) -> Optional[str]:
        return self._get("X_BEARER_TOKEN")

    @property
    def base_url(self) -> str:
        return self._get("X_BASE_URL") or self.DEFAULT_BASE_URL

    def has_bearer_token(self) -> bool:
        """Check if bearer token is available for read-only operations."""
        return bool(self.bearer_token)

    def test_connection(self) -> Optional[dict]:
        """Verify OAuth 1.0a credentials by calling /2/users/me."""
        from .client import XClient, ClientError
        try:
            client = XClient(config=self)
            user = client.get_me()
            return {
                "api_test": "passed",
                "user_id": user.get("id", ""),
                "username": user.get("username", ""),
                "name": user.get("name", ""),
            }
        except ClientError as e:
            return {"api_test": f"failed: {e}"}


_configs: dict = {}


def get_config(profile=None) -> Config:
    """Get or create a config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
