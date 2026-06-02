"""Configuration management for Podio CLI."""
import os
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from pypodio2 import RetryConfig


class Config(BaseConfig):
    """Podio CLI configuration.

    Uses OAuth authorization code flow (CLIENT_ID + CLIENT_SECRET + ACCESS_TOKEN).
    Supports multiple auth methods: token, authorization code, user/password, app.
    """

    DIST_NAME = "podio-cli"

    CREDENTIAL_TYPES = [CredentialType.OAUTH_AUTHORIZATION_CODE]
    DEFAULT_BASE_URL = "https://api.podio.com"

    OAUTH_AUTH_URL = "https://podio.com/oauth/authorize"
    OAUTH_TOKEN_URL = "https://podio.com/oauth/token"

    def __init__(self, profile=None):
        self._retry_config: Optional[RetryConfig] = None
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    # Podio-specific properties (beyond standard BaseConfig fields)
    @property
    def app_id(self) -> Optional[str]:
        return self._get("APP_ID")

    @property
    def app_token(self) -> Optional[str]:
        return self._get("APP_TOKEN")

    @property
    def organization_id(self) -> Optional[str]:
        return self._get("ORGANIZATION_ID")

    @property
    def workspace_id(self) -> Optional[str]:
        return self._get("WORKSPACE_ID")

    @property
    def authorization_code(self) -> Optional[str]:
        return self._get("AUTHORIZATION_CODE")

    def has_user_auth(self) -> bool:
        """Check if user authentication credentials are available."""
        return bool(
            self.client_id
            and self.client_secret
            and self.username
            and self.password
        )

    def has_app_auth(self) -> bool:
        """Check if app authentication credentials are available."""
        return bool(
            self.client_id
            and self.client_secret
            and self.app_id
            and self.app_token
        )

    def has_authorization_code_auth(self) -> bool:
        """Check if authorization code credentials are available."""
        return bool(
            self.client_id
            and self.client_secret
            and self.authorization_code
            and self.redirect_uri
        )

    def has_token_auth(self) -> bool:
        """Check if access token authentication is available."""
        return bool(self.access_token)

    def save_podio_tokens(self, access_token: str, refresh_token: str):
        """Save refreshed Podio tokens to the .env file."""
        self._set("ACCESS_TOKEN", access_token)
        if refresh_token:
            self._set("REFRESH_TOKEN", refresh_token)

    def test_connection(self) -> Optional[dict]:
        """Test API connectivity by fetching current user info."""
        from .client import get_client
        client = get_client(config=self)
        user = client.User.current()
        return {
            "api_test": "passed",
            "user_id": user.get("user_id"),
            "email": user.get("mail"),
        }

    def get_retry_config(self) -> RetryConfig:
        """Build (and cache) the retry configuration for outbound Podio requests."""
        if self._retry_config is not None:
            return self._retry_config

        max_retries = self._get_int_env("RETRY_MAX_ATTEMPTS", default=5, minimum=0)
        base_delay = self._get_float_env("RETRY_BASE_DELAY", default=2.0, minimum=0.001)
        max_delay = self._get_float_env("RETRY_MAX_DELAY", default=60.0, minimum=base_delay)
        exponential_base = self._get_float_env(
            "RETRY_EXPONENTIAL_BASE",
            default=2.0,
            minimum=1.001
        )
        jitter = self._get_bool_env("RETRY_JITTER", default=True)
        retry_on_rate_limit = self._get_bool_env("RETRY_ON_RATE_LIMIT", default=True)

        self._retry_config = RetryConfig(
            max_retries=max_retries,
            base_delay=base_delay,
            max_delay=max_delay,
            exponential_base=exponential_base,
            jitter=jitter,
            retry_on_rate_limit=retry_on_rate_limit
        )
        return self._retry_config

    def _get_int_env(self, name: str, default: int, minimum: Optional[int] = None) -> int:
        value = os.getenv(name)
        if value is None:
            return default
        try:
            parsed = int(value)
        except ValueError:
            raise ValueError(f"{name} must be an integer, got {value!r}")
        if minimum is not None and parsed < minimum:
            raise ValueError(f"{name} must be >= {minimum}, got {parsed}")
        return parsed

    def _get_float_env(self, name: str, default: float, minimum: Optional[float] = None) -> float:
        value = os.getenv(name)
        if value is None:
            return default
        try:
            parsed = float(value)
        except ValueError:
            raise ValueError(f"{name} must be a number, got {value!r}")
        if minimum is not None and parsed < minimum:
            raise ValueError(f"{name} must be >= {minimum}, got {parsed}")
        return parsed

    def _get_bool_env(self, name: str, default: bool) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        normalized = value.strip().lower()
        if normalized not in {"true", "false"}:
            raise ValueError(f"{name} must be either 'true' or 'false', got {value!r}")
        return normalized == "true"


_configs = {}


def get_config(profile=None) -> Config:
    """Get or create a config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
