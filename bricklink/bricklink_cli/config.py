"""Configuration management for Bricklink CLI.

Supports dual authentication:
- OAuth 1.0a API credentials (consumer key/secret + token/secret)
- Browser session (playwright CLI persistent profiles for messages/refunds)

OAuth 1.0a mapping to standard credential fields:
- CLIENT_ID       -> consumer key
- CLIENT_SECRET   -> consumer secret
- ACCESS_TOKEN    -> token value (resource owner key)
- REFRESH_TOKEN   -> token secret (resource owner secret)
"""
import os
from pathlib import Path

from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType

activity = get_activity_logger("bricklink")


class Config(BaseConfig):
    DIST_NAME = "bricklink-cli"
    CREDENTIAL_TYPES = [CredentialType.OAUTH, CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://api.bricklink.com/api/store/v1"
    OAUTH_TOKEN_EXPIRES = False
    OAUTH_STATIC_REQUIRED_FIELDS = ("CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN")

    AUTH_EXTRA_PROMPTS = [
        ("ACCESS_TOKEN", "Token Value", False),
        ("REFRESH_TOKEN", "Token Secret", True),
    ]

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def get_browser(self):
        """Return browser service for Bricklink browser-based auth."""
        from .browser_runtime import BricklinkRuntimeBrowser
        return BricklinkRuntimeBrowser(self)

    def _env_file_for_profile(self, name: str) -> Path:
        migrated_path = self.get_profiles_dir() / name / ".env"
        if migrated_path.exists():
            return migrated_path
        return super()._env_file_for_profile(name)

    # OAuth 1.0a properties using standard BaseConfig fields
    @property
    def consumer_key(self) -> str:
        return self.client_id or ""

    @property
    def consumer_secret(self) -> str:
        return self.client_secret or ""

    @property
    def token_value(self) -> str:
        return self.access_token or ""

    @property
    def token_secret(self) -> str:
        return self.refresh_token or ""

    def has_api_credentials(self) -> bool:
        """Check if OAuth 1.0a API credentials are configured."""
        has_creds = bool(
            self.consumer_key
            and self.consumer_secret
            and self.token_value
            and self.token_secret
        )
        if not has_creds:
            activity.warning("API credentials check failed — one or more OAuth1 fields missing")
        return has_creds

    @property
    def storage_dir(self) -> Path:
        """Get storage directory for the active profile (used by @cached decorator)."""
        return self.get_profile_data_dir()

_configs = {}


def get_config(profile=None):
    key = (profile or "_default", os.environ.get("XDG_DATA_HOME"))
    if key not in _configs:
        activity.info("Loading config profile=%s", profile or "default")
        _configs[key] = Config(profile=profile)
    return _configs[key]
