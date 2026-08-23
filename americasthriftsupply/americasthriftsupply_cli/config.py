"""Configuration management for Americasthriftsupply CLI."""

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.exceptions import ClientError


class Config(BaseConfig):
    DIST_NAME = "americasthriftsupply-cli"
    CREDENTIAL_TYPES = []
    DEFAULT_BASE_URL = "https://americasthriftsupply.com"
    # Uncomment when auth login needs required non-secret config first.
    # AUTH_CONFIG_PROMPTS = [("BASE_URL", "Americasthriftsupply base URL", False)]
    # Uncomment when the user must create a token/app before logging in.
    # AUTH_SETUP_INSTRUCTIONS = (
    #     "Before logging in:\n"
    #     "  1. Create the required token/app: https://example.com/settings/api\n"
    #     "  2. Follow the service instructions, then continue here."
    # )

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
        """Validate the public storefront API connection with a live call."""
        from .client import AmericasthriftsupplyClient

        try:
            AmericasthriftsupplyClient(config=self).list_products(limit=1)
            return {"api_test": "passed"}
        except ClientError as exc:
            return {"api_test": f"failed: {exc}"}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
