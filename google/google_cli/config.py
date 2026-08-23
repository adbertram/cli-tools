"""Configuration management for Google CLI."""
import os
from pathlib import Path
from typing import Optional
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Google CLI configuration - extends BaseConfig for profile support."""

    DIST_NAME = "google-cli"

    CREDENTIAL_TYPES = [CredentialType.CUSTOM, CredentialType.BROWSER_SESSION]
    CUSTOM_REQUIRED_FIELDS = ["CLIENT_ID", "CLIENT_SECRET"]
    CUSTOM_ALL_FIELDS = [
        "CLIENT_ID",
        "CLIENT_SECRET",
        "GOOGLE_SEARCHCONSOLE_SITE",
        "GOOGLE_ANALYTICS_PROPERTY_ID",
    ]
    LOGIN_INSTRUCTIONS = (
        "Create OAuth credentials at: https://console.cloud.google.com/apis/credentials\n"
        "  Click 'Create Credentials' > 'OAuth client ID' > type: 'Desktop app'\n"
        "  (Desktop app type auto-allows http://localhost redirect URIs)"
    )
    CUSTOM_LOGIN_PROMPTS = [
        ("CLIENT_ID", "OAuth Client ID", False),
        ("CLIENT_SECRET", "OAuth Client Secret", True),
    ]
    CUSTOM_EPHEMERAL_FIELDS = []
    CUSTOM_SENSITIVE_FIELDS = ["CLIENT_ID", "CLIENT_SECRET"]

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def has_credentials(self) -> bool:
        """Credentials exist when token.json is present in the profile data dir."""
        return self.token_path_obj.exists()

    def get_missing_credentials(self) -> list[str]:
        """Return missing OAuth client setup values."""
        missing = []
        if not self._get("CLIENT_ID"):
            missing.append("CLIENT_ID")
        if not self._get("CLIENT_SECRET"):
            missing.append("CLIENT_SECRET")
        return missing

    def get_browser(self):
        """Return Chrome Web Store dashboard browser automation."""
        from .browser import ChromeWebStoreBrowser
        return ChromeWebStoreBrowser(self)

    @property
    def token_path_obj(self) -> Path:
        """Resolved Path for token.json in the active profile's data dir."""
        return self.get_profile_data_dir() / "token.json"

    @property
    def token_path(self) -> str:
        """String path to token.json (for GoogleClient compatibility)."""
        return str(self.token_path_obj)

    def oauth_client_config(self) -> dict:
        """Build the Google OAuth client config without writing secrets to disk."""
        client_id = self._get("CLIENT_ID")
        client_secret = self._get("CLIENT_SECRET")
        if not client_id or not client_secret:
            missing = ", ".join(self.get_missing_credentials())
            raise ValueError(f"Missing OAuth client setup values: {missing}")
        return {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uris": ["http://localhost", "urn:ietf:wg:oauth:2.0:oob"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }

    def test_connection(self) -> Optional[dict]:
        """Test API connectivity and return the authenticated user's email.

        Uses the Drive API about().get() endpoint to retrieve the email
        address of the authenticated Google account. This lets `auth status`
        show which account the token belongs to, so users can detect when
        they've authenticated with the wrong Google account.
        """
        from .client import get_client
        from googleapiclient.errors import HttpError
        try:
            client = get_client(profile=self.get_active_profile_name())
            service = client.get_drive_service()
            about = service.about().get(fields="user").execute()
            email = about.get("user", {}).get("emailAddress", "unknown")
            return {"api_test": "passed", "email": email}
        except HttpError as e:
            return {"api_test": f"failed: {e}"}
        except Exception as e:
            return {"api_test": f"failed: {e}"}

    @property
    def searchconsole_site(self) -> Optional[str]:
        """Get Search Console site URL from environment."""
        return os.getenv("GOOGLE_SEARCHCONSOLE_SITE")

    @property
    def analytics_property_id(self) -> Optional[str]:
        """Get default GA4 property ID from environment."""
        return os.getenv("GOOGLE_ANALYTICS_PROPERTY_ID")


_configs: dict = {}


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create a config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]


def reset_config():
    """Reset all config instances (for testing)."""
    global _configs
    _configs = {}
