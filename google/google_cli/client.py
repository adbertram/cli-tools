"""Google API service client."""
import json
import os.path
import time
import random
from typing import Any, Optional, Callable
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from .config import get_config

# Define scopes for different Google services
SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/webmasters",
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/chat.spaces.readonly",
    "https://www.googleapis.com/auth/chat.messages.readonly",
    "https://www.googleapis.com/auth/chat.messages",
    "https://www.googleapis.com/auth/chat.memberships.readonly",
    "https://www.googleapis.com/auth/chromewebstore",
    "https://www.googleapis.com/auth/datastudio",
    "https://www.googleapis.com/auth/contacts.readonly",
]

class ClientError(Exception):
    """Custom exception for client errors."""
    pass


def _missing_oauth_scopes(token_scopes: list[str]) -> list[str]:
    """Return required OAuth scopes absent from stored credentials."""
    stored_scopes = set(token_scopes)
    if not stored_scopes:
        return []
    return [scope for scope in SCOPES if scope not in stored_scopes]


def _load_stored_oauth_scopes(token_path: str) -> list[str]:
    """Load OAuth scopes exactly as stored in token.json."""
    with open(token_path) as token_file:
        token_data = json.load(token_file)
    return token_data.get("scopes", [])


def get_browser(config=None):
    """Return the shared browser automation service for dashboard-only surfaces."""
    resolved_config = config or get_config()
    return resolved_config.get_browser()


def retry_with_exponential_backoff(
    func: Callable,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0
) -> Any:
    """Retry a function with exponential backoff and jitter.

    Args:
        func: The function to retry
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds

    Returns:
        The result of the function call

    Raises:
        The last exception encountered if all retries fail
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return func()
        except HttpError as e:
            last_exception = e

            # Don't retry on client errors (4xx) except for 429 (rate limit)
            if e.resp.status >= 400 and e.resp.status < 500 and e.resp.status != 429:
                raise

            # Don't retry on the last attempt
            if attempt == max_retries:
                raise

            # Calculate delay with exponential backoff and jitter
            delay = min(base_delay * (2 ** attempt), max_delay)
            jitter = random.uniform(0, delay * 0.1)  # 10% jitter
            total_delay = delay + jitter

            time.sleep(total_delay)

    # This should never be reached, but just in case
    if last_exception:
        raise last_exception

class GoogleClient:
    """Client for Google Workspace APIs."""

    def __init__(self, config):
        self.config = config
        missing = self.config.get_missing_credentials()
        if missing:
            raise ClientError(f"Missing credentials: {', '.join(missing)}")

        self.creds = None
        self._authenticate()

    def _authenticate(self):
        """Authenticate with Google OAuth2."""
        # Load existing token if available
        if os.path.exists(self.config.token_path):
            missing_scopes = _missing_oauth_scopes(
                _load_stored_oauth_scopes(self.config.token_path)
            )
            if missing_scopes:
                raise ClientError(
                    "Stored Google token is missing required OAuth scopes: "
                    + ", ".join(missing_scopes)
                    + ". Run 'google auth login --force' to re-authenticate."
                )
            self.creds = Credentials.from_authorized_user_file(self.config.token_path, SCOPES)

        # If there are no (valid) credentials available, let the user log in
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_config(
                    self.config.oauth_client_config(), SCOPES
                )
                self.creds = flow.run_local_server(port=0)

            # Save the credentials for the next run
            with open(self.config.token_path, "w") as token:
                token.write(self.creds.to_json())

    def get_service(self, service_name: str, version: str):
        """Build and return a Google API service.

        Args:
            service_name: Name of the service (e.g., 'docs', 'drive', 'sheets')
            version: API version (e.g., 'v1', 'v3')

        Returns:
            Google API service object
        """
        try:
            return build(service_name, version, credentials=self.creds)
        except HttpError as error:
            raise ClientError(f"Failed to build {service_name} service: {error}")

    def get_docs_service(self):
        """Get Google Docs service."""
        return self.get_service("docs", "v1")

    def get_drive_service(self):
        """Get Google Drive service."""
        return self.get_service("drive", "v3")

    def get_sheets_service(self):
        """Get Google Sheets service."""
        return self.get_service("sheets", "v4")

    def get_gmail_service(self):
        """Get Gmail service."""
        return self.get_service("gmail", "v1")

    def get_calendar_service(self):
        """Get Google Calendar service."""
        return self.get_service("calendar", "v3")

    def get_people_service(self):
        """Get Google People service."""
        return self.get_service("people", "v1")

    def get_webmasters_service(self):
        """Get Google Search Console v1 service (for URL Inspection API)."""
        return self.get_service("searchconsole", "v1")

    def get_webmasters_v3_service(self):
        """Get Google Webmasters v3 service (for Search Analytics API)."""
        return self.get_service("webmasters", "v3")

    def get_cloud_resource_manager_service(self):
        """Get Google Cloud Resource Manager v3 service."""
        return self.get_service("cloudresourcemanager", "v3")

    def get_iam_service(self):
        """Get Google Cloud IAM v1 service."""
        return self.get_service("iam", "v1")

    def get_api_keys_service(self):
        """Get Google Cloud API Keys v2 service."""
        return self.get_service("apikeys", "v2")

    def get_service_usage_service(self):
        """Get Google Cloud Service Usage v1 service."""
        return self.get_service("serviceusage", "v1")

    def get_analytics_data_service(self):
        """Get Google Analytics Data API service."""
        return self.get_service("analyticsdata", "v1beta")

    def get_analytics_admin_service(self):
        """Get Google Analytics Admin API service."""
        return self.get_service("analyticsadmin", "v1beta")

    def get_chat_service(self):
        """Get Google Chat service."""
        return self.get_service("chat", "v1")

_clients: dict = {}


def get_client(profile: Optional[str] = None) -> GoogleClient:
    """Get or create the client instance for the given profile."""
    key = profile or "_default"
    if key not in _clients:
        config = get_config(profile=profile)
        _clients[key] = GoogleClient(config)
    return _clients[key]


def reset_client():
    """Reset all client instances (for testing)."""
    global _clients
    _clients = {}
