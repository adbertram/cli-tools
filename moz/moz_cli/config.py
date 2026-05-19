"""Configuration management for Moz CLI."""
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Moz CLI configuration (API key auth via x-moz-token header)."""

    DIST_NAME = "moz-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DEFAULT_BASE_URL = "https://api.moz.com/jsonrpc"
    CUSTOM_REQUIRED_FIELDS = ["MOZ_API_KEY"]
    CUSTOM_SENSITIVE_FIELDS = ["MOZ_API_KEY"]

    LOGIN_INSTRUCTIONS = (
        "To get your Moz API key:\n"
        "  1. Go to https://moz.com/products/api\n"
        "  2. Sign in and locate your API credentials\n"
        "  3. Copy the API token string"
    )

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def api_key(self) -> Optional[str]:
        return self._get("MOZ_API_KEY")

    @property
    def base_url(self) -> str:
        return self._get("MOZ_BASE_URL") or self.DEFAULT_BASE_URL

    def test_connection(self) -> Optional[dict]:
        """Verify the API key with a lightweight JSON-RPC call."""
        from .client import MozClient, ClientError
        try:
            client = MozClient(config=self)
            client._make_jsonrpc_request(
                "data.keyword.metrics.fetch",
                {
                    "serp_query": {
                        "keyword": "moz",
                        "locale": "en-US",
                        "device": "desktop",
                        "engine": "google",
                    }
                },
                retry=False,
            )
            return {"api_test": "passed"}
        except ClientError as e:
            return {"api_test": f"failed: {e}"}


_configs: dict = {}


def get_config(profile=None) -> Config:
    """Get or create a config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
