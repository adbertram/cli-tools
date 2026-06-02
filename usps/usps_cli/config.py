"""Configuration management for USPS CLI."""
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """USPS CLI configuration (OAuth client credentials)."""

    DIST_NAME = "usps-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS = ["USPS_CLIENT_ID", "USPS_CLIENT_SECRET"]
    CUSTOM_ALL_FIELDS = [
        "USPS_CLIENT_ID",
        "USPS_CLIENT_SECRET",
        "USPS_ACCESS_TOKEN",
        "USPS_TOKEN_EXPIRES_AT",
    ]
    CUSTOM_LOGIN_PROMPTS = [
        ("USPS_CLIENT_ID", "USPS Client ID", False),
        ("USPS_CLIENT_SECRET", "USPS Client Secret", True),
    ]
    CUSTOM_EPHEMERAL_FIELDS = ["USPS_ACCESS_TOKEN", "USPS_TOKEN_EXPIRES_AT"]
    CUSTOM_SENSITIVE_FIELDS = [
        "USPS_CLIENT_SECRET",
        "USPS_ACCESS_TOKEN",
    ]

    LOGIN_INSTRUCTIONS = (
        "To get USPS API credentials:\n"
        "  1. Go to https://developer.usps.com\n"
        "  2. Create an app with Tracking API access\n"
        "  3. Paste the client ID and client secret below"
    )

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def client_id(self) -> Optional[str]:
        return self._get("USPS_CLIENT_ID")

    @property
    def client_secret(self) -> Optional[str]:
        return self._get("USPS_CLIENT_SECRET")

    @property
    def access_token(self) -> Optional[str]:
        return self._get("USPS_ACCESS_TOKEN")

    @property
    def token_expires_at(self) -> Optional[str]:
        return self._get("USPS_TOKEN_EXPIRES_AT")

    @property
    def oauth_url(self) -> str:
        return "https://apis.usps.com/oauth2/v3/token"

    @property
    def tracking_api_url(self) -> str:
        return "https://apis.usps.com/tracking/v3/tracking"

    def save_access_token(self, access_token: str, expires_at: str):
        """Save access token for the client token cache."""
        self._set("USPS_ACCESS_TOKEN", access_token)
        self._set("USPS_TOKEN_EXPIRES_AT", expires_at)

    def save_credentials(self, client_id: str, client_secret: str):
        """Compatibility helper for existing callers."""
        self._set("USPS_CLIENT_ID", client_id)
        self._set("USPS_CLIENT_SECRET", client_secret)

    def test_connection(self) -> Optional[dict]:
        """Verify credentials by requesting an OAuth access token."""
        from .client import UspsClient, ClientError
        try:
            UspsClient(config=self).validate_credentials()
            return {"api_test": "passed"}
        except ClientError as e:
            return {"api_test": f"failed: {e}"}


_configs: dict = {}


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create a config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
