"""Configuration management for Venmo CLI."""
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    DIST_NAME = "venmo-cli"

    # Venmo has no public API. We use the reverse-engineered venmo-api
    # library which authenticates via username+password+SMS-OTP and
    # returns a long-lived access token. Username and password are
    # pulled from the CLI-tools keychain (venmo-username / venmo-password)
    # by the custom login_handler; the resulting ACCESS_TOKEN and
    # DEVICE_ID are persisted to the per-profile .env. Subsequent
    # data commands need only the ACCESS_TOKEN.
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DEFAULT_BASE_URL = "https://api.venmo.com"

    # No interactive prompts — credentials come from the keychain.
    CUSTOM_LOGIN_PROMPTS: list = []

    # Persisted post-login. Required for data commands to call the API.
    CUSTOM_REQUIRED_FIELDS = ["ACCESS_TOKEN"]
    # Ephemeral so `auth login --force` and `auth logout` clear them.
    CUSTOM_EPHEMERAL_FIELDS = ["ACCESS_TOKEN", "DEVICE_ID"]
    CUSTOM_ALL_FIELDS = ["ACCESS_TOKEN", "DEVICE_ID"]
    CUSTOM_SENSITIVE_FIELDS = ["ACCESS_TOKEN"]

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def device_id(self) -> Optional[str]:
        return self._get("DEVICE_ID")

    @property
    def storage_dir(self) -> Path:
        """Directory used by the shared @cached decorator for response cache files."""
        return self.get_profile_data_dir()


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
