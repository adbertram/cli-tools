"""Configuration management for Fedex CLI."""
from pathlib import Path
from typing import Optional
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for FedEx CLI - OAuth client credentials flow."""

    DIST_NAME = "fedex-cli"

    CREDENTIAL_TYPES = [CredentialType.OAUTH]
    DEFAULT_BASE_URL = "https://apis.fedex.com"
    OAUTH_TOKEN_URL = "https://apis.fedex.com/oauth/token"
    OAUTH_TOKEN_EXPIRES = False

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def has_credentials(self) -> bool:
        """Check if static OAuth credentials are configured.

        FedEx uses client_credentials flow - ACCESS_TOKEN is obtained
        automatically, so we only check CLIENT_ID and CLIENT_SECRET.
        """
        return bool(self.client_id and self.client_secret)

    def get_missing_credentials(self) -> list:
        """Get list of missing static credentials."""
        missing = []
        if not self.client_id:
            missing.append("CLIENT_ID")
        if not self.client_secret:
            missing.append("CLIENT_SECRET")
        return missing

    def test_connection(self) -> Optional[dict]:
        """Test API connection by requesting an OAuth token."""
        import requests
        try:
            response = requests.post(
                self.OAUTH_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
            if response.ok:
                return {"api_test": "passed", "base_url": self.base_url}
            return {"api_test": f"failed: HTTP {response.status_code}"}
        except requests.exceptions.RequestException as e:
            return {"api_test": f"failed: {e}"}

    # ==================== FedEx-specific defaults ====================

    @property
    def default_street(self) -> Optional[str]:
        return self._get("DEFAULT_STREET")

    @property
    def default_city(self) -> Optional[str]:
        return self._get("DEFAULT_CITY")

    @property
    def default_state(self) -> Optional[str]:
        return self._get("DEFAULT_STATE")

    @property
    def default_postal(self) -> Optional[str]:
        return self._get("DEFAULT_POSTAL")

    @property
    def default_residential(self) -> bool:
        return (self._get("DEFAULT_RESIDENTIAL") or "").lower() in ("true", "1", "yes")

    @property
    def default_carrier(self) -> str:
        return self._get("DEFAULT_CARRIER") or "FDXE"

    @property
    def default_account(self) -> Optional[str]:
        return self._get("DEFAULT_ACCOUNT")

    @property
    def default_package_location(self) -> Optional[str]:
        return self._get("DEFAULT_PACKAGE_LOCATION")


def get_config(profile=None) -> Config:
    """Get a Config instance for the given profile."""
    return Config(profile=profile)
