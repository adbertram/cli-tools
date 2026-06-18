"""Configuration management for PayPal CLI."""
from pathlib import Path
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):

    DIST_NAME = "paypal-cli"
    CREDENTIAL_TYPES = [CredentialType.OAUTH, CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://api-m.paypal.com"
    OAUTH_TOKEN_EXPIRES = False
    OAUTH_STATIC_REQUIRED_FIELDS = ("CLIENT_ID", "CLIENT_SECRET")

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def api_base_url(self) -> str:
        """Get PayPal API base URL."""
        return self.base_url or self.DEFAULT_BASE_URL

    @property
    def storage_dir(self) -> Path:
        """Get profile data directory used by shared cache helpers."""
        return self.get_profile_data_dir()

    def has_credentials(self) -> bool:
        """Check if API credentials are configured."""
        return bool(self.client_id and self.client_secret)

    def get_missing_credentials(self) -> list:
        """Get list of missing API credentials."""
        missing = []
        if not self.client_id:
            missing.append("CLIENT_ID")
        if not self.client_secret:
            missing.append("CLIENT_SECRET")
        return missing

    def test_connection(self) -> dict:
        """Test API credentials by requesting an OAuth token."""
        import requests
        import base64
        credentials = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        response = requests.post(
            f"{self.api_base_url}/v1/oauth2/token",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data="grant_type=client_credentials",
            timeout=10,
        )
        if response.ok:
            data = response.json()
            return {
                "api_test": "passed",
                "app_id": data.get("app_id", ""),
                "scope": data.get("scope", "")[:100],
            }
        return {"api_test": f"failed: HTTP {response.status_code}"}

    def get_browser(self):
        """Return browser service for PayPal browser-based auth."""
        from .browser import PayPalBrowser

        return PayPalBrowser(self)


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
