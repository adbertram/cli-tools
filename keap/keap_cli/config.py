"""Configuration management for Keap CLI."""
from cli_tools_shared.config import BaseConfig
from cli_tools_shared.config import resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    DIST_NAME = "keap-cli"
    CREDENTIAL_TYPES = [CredentialType.OAUTH]
    DEFAULT_BASE_URL = "https://keap.com/"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    # Uncomment for dual-auth CLIs (API + browser_session):
    # def has_api_credentials(self) -> bool:
    #     """Check if API credentials are configured (ignores browser session)."""
    #     return bool(self.api_key)

    def test_connection(self) -> dict:
        """Expose an auth test command for the initial scaffold."""
        if not self.has_credentials():
            return {"api_test": "failed: credentials not configured"}
        return {
            "api_test": (
                "failed: live verification requires a service-specific API base URL "
                "and valid Keap credentials"
            )
        }


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
