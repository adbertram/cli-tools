"""Configuration management for eBay CLI."""
import shutil
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration manager for eBay CLI authentication and settings."""

    DIST_NAME = "ebay-cli"

    CREDENTIAL_TYPE = CredentialType.OAUTH_AUTHORIZATION_CODE
    CREDENTIAL_TYPES = [CredentialType.OAUTH_AUTHORIZATION_CODE]
    DEFAULT_BASE_URL = "https://api.ebay.com"

    # OAuth 2.0 configuration
    OAUTH_SCOPES = [
        "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
        "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
        "https://api.ebay.com/oauth/api_scope/commerce.identity.readonly",
        "https://api.ebay.com/oauth/api_scope/sell.inventory",
        "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
        "https://api.ebay.com/oauth/api_scope/sell.account",
        "https://api.ebay.com/oauth/api_scope/sell.account.readonly",
        "https://api.ebay.com/oauth/api_scope/sell.stores",
        "https://api.ebay.com/oauth/api_scope/sell.logistics",
    ]
    OAUTH_TOKEN_AUTH = "basic"  # eBay uses Authorization: Basic header

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    # ==================== eBay-Specific Properties ====================

    @property
    def OAUTH_AUTH_URL(self) -> str:
        """eBay auth URL varies by environment (sandbox vs production)."""
        return f"{self.auth_base_url}/oauth2/authorize"

    @property
    def OAUTH_TOKEN_URL(self) -> str:
        """eBay token URL varies by environment (sandbox vs production)."""
        return f"{self.api_base_url}/identity/v1/oauth2/token"

    @property
    def environment(self) -> str:
        """Get eBay API environment (sandbox or production)."""
        return self._get("ENVIRONMENT") or "production"

    @property
    def api_base_url(self) -> str:
        """Get eBay API base URL based on environment."""
        if self.environment == "sandbox":
            return "https://api.sandbox.ebay.com"
        return "https://api.ebay.com"

    @property
    def auth_base_url(self) -> str:
        """Get eBay auth base URL based on environment."""
        if self.environment == "sandbox":
            return "https://auth.sandbox.ebay.com"
        return "https://auth.ebay.com"

    def has_oauth_credentials(self) -> bool:
        """Check if OAuth credentials are available."""
        return bool(
            self.client_id
            and self.client_secret
            and self.access_token
        )

    def get_missing_credentials(self) -> list[str]:
        """Get list of missing credentials."""
        missing = []
        if not self.client_id:
            missing.append("CLIENT_ID")
        if not self.client_secret:
            missing.append("CLIENT_SECRET")
        if not self.access_token:
            missing.append("ACCESS_TOKEN")
        return missing

    def clear_tokens(self):
        """Clear OAuth tokens (but keep app credentials)."""
        self._clear("ACCESS_TOKEN")
        self._clear("REFRESH_TOKEN")
        self._clear("TOKEN_EXPIRES_AT")

    def test_connection(self) -> dict:
        """Test API connectivity by fetching user info."""
        import requests
        from cli_tools_shared.token_manager import TokenManager

        tokens = TokenManager(self, on_refresh=lambda: None)
        if tokens.is_expired():
            try:
                tokens.force_refresh()
            except Exception:
                pass

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        base_url = self.api_base_url.replace("api.", "apiz.")
        url = f"{base_url}/commerce/identity/v1/user/"

        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.ok:
                data = response.json()
                return {
                    "api_test": "passed",
                    "username": data.get("username", "unknown"),
                }
            return {"api_test": f"failed: HTTP {response.status_code}"}
        except Exception as e:
            return {"api_test": f"failed: {e}"}

    # ==================== Browser Session Properties ====================

    @property
    def browser_login_url(self) -> str:
        """URL for browser-based login."""
        return "https://www.ebay.com"

    @property
    def headless(self) -> bool:
        """Get headless browser mode setting."""
        return (self._get("HEADLESS") or "true").lower() == "true"

    @property
    def auth_indicator_selector(self) -> Optional[str]:
        """CSS selector that should exist when logged in."""
        return self._get("AUTH_INDICATOR_SELECTOR")

    @property
    def login_redirect_pattern(self) -> Optional[str]:
        """URL pattern that indicates redirect to login page."""
        return self._get("LOGIN_REDIRECT_PATTERN")

    @property
    def storage_dir(self) -> Path:
        """Get storage directory for the active profile."""
        return self.get_profile_data_dir()

    def get_browser(self):
        """Return BrowserService for browser-based authentication."""
        from .browser import BrowserService
        return BrowserService(self)

    def clear_session(self):
        """Clear saved session data."""
        super().clear_session()

    # ==================== Ship-From Address ====================

    def get_from_name(self, profile: Optional[str] = None) -> Optional[str]:
        return self._get("FROM_NAME")

    def get_from_street(self, profile: Optional[str] = None) -> Optional[str]:
        return self._get("FROM_STREET")

    def get_from_city(self, profile: Optional[str] = None) -> Optional[str]:
        return self._get("FROM_CITY")

    def get_from_state(self, profile: Optional[str] = None) -> Optional[str]:
        return self._get("FROM_STATE")

    def get_from_zip(self, profile: Optional[str] = None) -> Optional[str]:
        return self._get("FROM_ZIP")

    def get_from_country(self, profile: Optional[str] = None) -> str:
        return self._get("FROM_COUNTRY") or "US"

    def get_from_phone(self, profile: Optional[str] = None) -> Optional[str]:
        return self._get("FROM_PHONE")


# Singleton cache keyed by profile name
_configs: dict[str, Config] = {}


def get_config(profile=None) -> Config:
    """Get or create config for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
