"""Configuration management for OneDrive CLI."""
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration manager for OneDrive CLI with profile support.

    Uses one CUSTOM credential type where AUTH_METHOD determines how tokens are obtained:
    - 'az_cli': via Azure CLI (az account get-access-token)
    - 'msal_device_code': via MSAL device code flow

    AUTH_METHOD is runtime configuration inside one auth model, not a separate
    profile auth type. Commands should run against the active profile without
    requiring an explicit --profile just because different profiles choose
    different token acquisition methods.

    An msal_device_code profile may also set TENANT_ID to authenticate against
    a specific Microsoft Entra tenant instead of the multi-tenant /common
    endpoint -- for example, a tenant a client shared a OneDrive/SharePoint
    resource from. TENANT_ID is optional; profiles that omit it keep using
    /common exactly as before.
    """

    DIST_NAME = "onedrive-cli"

    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DEFAULT_BASE_URL = "https://graph.microsoft.com/v1.0"

    # CUSTOM credential type: AUTH_METHOD is the only required field.
    # TENANT_ID is optional per-profile authority scoping (msal_device_code only).
    CUSTOM_REQUIRED_FIELDS = ["AUTH_METHOD"]
    CUSTOM_ALL_FIELDS = ["AUTH_METHOD", "TENANT_ID"]
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

    @property
    def tenant_id(self) -> Optional[str]:
        """Get the profile's tenant authority override, if set.

        When set, msal_device_code auth uses this Microsoft Entra tenant's
        authority (https://login.microsoftonline.com/<tenant_id>) instead of
        the multi-tenant /common endpoint. Unset by default, preserving the
        existing /common behavior for every other profile.
        """
        return self._get("TENANT_ID")

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
