"""Configuration management for Crypto.com Exchange CLI."""
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    DIST_NAME = "cryptocom-cli"
    DEFAULT_BASE_URL = "https://api.crypto.com/exchange/v1"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CREDENTIAL_PROMPTS = [
        ("API_KEY", "Crypto.com Exchange API key", True),
        ("API_SECRET", "Crypto.com Exchange API secret", True),
    ]
    CUSTOM_REQUIRED_FIELDS = ["API_KEY", "API_SECRET"]
    CUSTOM_ALL_FIELDS = ["API_KEY", "API_SECRET", "BASE_URL"]
    CUSTOM_LOGIN_PROMPTS = CREDENTIAL_PROMPTS
    AUTH_EXTRA_PROMPTS = CREDENTIAL_PROMPTS
    CUSTOM_SENSITIVE_FIELDS = ["API_KEY", "API_SECRET"]
    LOGIN_INSTRUCTIONS = (
        "Create an Exchange API key in Crypto.com Exchange User Center > API. "
        "This CLI needs the API key and secret key for private account commands."
    )

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def api_secret(self):
        """Get Crypto.com Exchange API secret."""
        return self._get("API_SECRET")

    def test_connection(self):
        """Verify credentials with a lightweight private Exchange API request."""
        from .client import CryptocomClient

        CryptocomClient(config=self).get_balances()
        return {"api_test": "passed"}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
