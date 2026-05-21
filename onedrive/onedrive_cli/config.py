"""Configuration management for OneDrive CLI."""
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration manager for OneDrive CLI with profile support.

    Uses CUSTOM credential type where AUTH_METHOD is the only required field.
    AUTH_METHOD determines how tokens are obtained:
    - 'az_cli': via Azure CLI (az account get-access-token)
    - 'msal_device_code': via MSAL device code flow
    """

    DIST_NAME = "onedrive-cli"

    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DEFAULT_BASE_URL = "https://graph.microsoft.com/v1.0"
    PROFILE_AUTH_TYPE_FIELD = "AUTH_METHOD"
    PROFILE_AUTH_TYPES = {
        "az_cli": [],
        "msal_device_code": [],
    }

    # CUSTOM credential type: AUTH_METHOD is the only required field
    CUSTOM_REQUIRED_FIELDS = ["AUTH_METHOD"]
    CUSTOM_ALL_FIELDS = ["AUTH_METHOD"]
    CUSTOM_LOGIN_PROMPTS = []  # login is handled by auth commands, not prompts
    CUSTOM_EPHEMERAL_FIELDS = []
    CUSTOM_SENSITIVE_FIELDS = []

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def auth_method(self) -> Optional[str]:
        """Get auth method: 'az_cli' or 'msal_device_code'."""
        return self._get("AUTH_METHOD")

    def test_connection(self) -> Optional[dict]:
        """Test API connectivity by acquiring a token."""
        from .msal_auth import test_handler
        return test_handler(self)


_config: Optional[Config] = None


def get_config(profile: str = None) -> Config:
    """Get or create the global config instance.

    Args:
        profile: Optional profile name. If provided, creates a new Config
                 for that profile. If None, returns cached default config.
    """
    global _config
    if _config is None or profile is not None:
        _config = Config(profile=profile)
    return _config
