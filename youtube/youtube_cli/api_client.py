"""YouTube Data API v3 client (OAuth-authenticated).

This client is separate from the yt-dlp wrapper in client.py. It is used
for authenticated channel-management operations: list/get/upload/update/delete
videos on the user's own channel.
"""
import json
import os.path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import get_config


# YouTube Data API v3 scopes for channel management.
# - youtube: full read/write access to the authenticated user's account
#   (covers list/get/update/delete videos, playlists, etc.)
# - youtube.upload: upload new videos
# - youtube.force-ssl: required for thumbnail upload
SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


class ApiClientError(Exception):
    """Raised for YouTube Data API client errors."""

    pass


def _missing_oauth_scopes(token_scopes: list) -> list:
    """Return required OAuth scopes absent from stored credentials."""
    stored = set(token_scopes)
    if not stored:
        return []
    return [scope for scope in SCOPES if scope not in stored]


def _load_stored_oauth_scopes(token_path: str) -> list:
    """Load OAuth scopes exactly as stored in token.json."""
    with open(token_path) as f:
        return json.load(f).get("scopes", [])


class YouTubeApiClient:
    """OAuth-authenticated client for the YouTube Data API v3."""

    def __init__(self, config):
        self.config = config
        missing = self.config.get_missing_credentials()
        if missing:
            raise ApiClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'youtube auth login' to authenticate."
            )

        self.creds = None
        self._authenticate()

    def _authenticate(self):
        """Authenticate with Google OAuth2.

        Loads token.json if present, refreshes it if expired, otherwise runs
        the InstalledAppFlow against the saved credentials.json.
        """
        if os.path.exists(self.config.token_path):
            missing_scopes = _missing_oauth_scopes(
                _load_stored_oauth_scopes(self.config.token_path)
            )
            if missing_scopes:
                raise ApiClientError(
                    "Stored YouTube token is missing required OAuth scopes: "
                    + ", ".join(missing_scopes)
                    + ". Run 'youtube auth login --force' to re-authenticate."
                )
            self.creds = Credentials.from_authorized_user_file(
                self.config.token_path, SCOPES
            )

        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.config.credentials_path, SCOPES
                )
                self.creds = flow.run_local_server(port=0)

            with open(self.config.token_path, "w") as f:
                f.write(self.creds.to_json())

    def get_youtube_service(self):
        """Return a built YouTube Data API v3 service object."""
        try:
            return build("youtube", "v3", credentials=self.creds)
        except HttpError as e:
            raise ApiClientError(f"Failed to build youtube service: {e}")


_clients: dict = {}


def get_api_client(profile: Optional[str] = None) -> YouTubeApiClient:
    """Get or create the API client instance for the given profile."""
    key = profile or "_default"
    if key not in _clients:
        config = get_config(profile=profile)
        _clients[key] = YouTubeApiClient(config)
    return _clients[key]


def reset_api_client():
    """Reset all API client instances (for testing)."""
    global _clients
    _clients = {}
