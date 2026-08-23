"""Configuration management for Youtube CLI."""
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType

YOUTUBE_PROFILE_AUTH_TYPE = "google_oauth_desktop"
YOUTUBE_PROFILE_AUTH_PROMPTS = (
    ("CLIENT_ID", "OAuth Client ID", False),
    ("CLIENT_SECRET", "OAuth Client Secret", True),
)


class Config(BaseConfig):
    """Configuration manager for Youtube CLI.

    Stores OAuth client credentials (CLIENT_ID/CLIENT_SECRET) for the
    YouTube Data API v3 + Upload scopes, plus the resulting token.json
    in the active profile's data directory.
    """

    DIST_NAME = "youtube-cli"

    CREDENTIAL_TYPES = [CredentialType.CUSTOM, CredentialType.BROWSER_SESSION]
    CUSTOM_REQUIRED_FIELDS = ["CLIENT_ID", "CLIENT_SECRET"]
    CUSTOM_ALL_FIELDS = ["AUTH_TYPE", "CLIENT_ID", "CLIENT_SECRET"]
    PROFILE_AUTH_TYPE_FIELD = "AUTH_TYPE"
    PROFILE_AUTH_TYPES = {
        YOUTUBE_PROFILE_AUTH_TYPE: YOUTUBE_PROFILE_AUTH_PROMPTS,
    }
    LOGIN_INSTRUCTIONS = (
        "Create OAuth credentials at: https://console.cloud.google.com/apis/credentials\n"
        "  Click 'Create Credentials' > 'OAuth client ID' > type: 'Desktop app'\n"
        "  (Desktop app type auto-allows http://localhost redirect URIs)\n"
        "  Then enable the YouTube Data API v3 in the same project."
    )
    CUSTOM_LOGIN_PROMPTS = YOUTUBE_PROFILE_AUTH_PROMPTS
    CUSTOM_EPHEMERAL_FIELDS = []
    CUSTOM_SENSITIVE_FIELDS = ["CLIENT_SECRET"]

    DEFAULT_BASE_URL = "https://www.youtube.com"

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def has_credentials(self) -> bool:
        """Credentials exist when token.json is present in the profile data dir."""
        return self.token_path_obj.exists()

    def get_missing_credentials(self) -> list:
        """Return list of what's missing for client initialization."""
        missing = []
        if not self.credentials_path:
            missing.append("credentials.json in profile data dir")
        return missing

    @property
    def token_path_obj(self) -> Path:
        """Resolved Path for token.json in the active profile's data dir."""
        return self.get_profile_data_dir() / "token.json"

    @property
    def token_path(self) -> str:
        """String path to token.json (for YouTubeApiClient compatibility)."""
        return str(self.token_path_obj)

    @property
    def headless(self) -> bool:
        """Whether browser-session commands should run without a visible window."""
        val = self._get("HEADLESS")
        return val is None or val.lower() == "true"

    @property
    def credentials_path(self) -> Optional[str]:
        """String path to credentials.json in the active profile's data dir."""
        profile_creds = self.get_profile_data_dir() / "credentials.json"
        if profile_creds.exists():
            return str(profile_creds)
        return None

    def test_connection(self) -> Optional[dict]:
        """Test API connectivity and return the authenticated user's channel."""
        from .api_client import get_api_client
        from googleapiclient.errors import HttpError
        try:
            client = get_api_client(profile=self.get_active_profile_name())
            service = client.get_youtube_service()
            response = service.channels().list(part="snippet", mine=True).execute()
            items = response.get("items", [])
            if not items:
                return {"api_test": "failed: no channel found for authenticated user"}
            channel = items[0]
            return {
                "api_test": "passed",
                "channel_id": channel["id"],
                "channel_title": channel["snippet"]["title"],
            }
        except HttpError as e:
            return {"api_test": f"failed: {e}"}
        except Exception as e:
            return {"api_test": f"failed: {e}"}

    def get_browser(self):
        """Return browser automation for YouTube web-only channel actions."""
        from .browser import YouTubeBrowser

        return YouTubeBrowser(self)


_configs: dict = {}


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create the global config instance."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]


def reset_config():
    """Reset all config instances (for testing)."""
    global _configs
    _configs = {}
