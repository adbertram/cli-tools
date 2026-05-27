"""Configuration management for Grammarly CLI."""
import os
import re
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Grammarly CLI configuration.

    Plagiarism API calls use custom OAuth client credentials. Docs API calls
    use a separate cookie-backed browser-session credential path.
    """

    DIST_NAME = "grammarly-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM, CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://api.grammarly.com"
    CUSTOM_REQUIRED_FIELDS = ["GRAMMARLY_CLIENT_ID", "GRAMMARLY_CLIENT_SECRET"]
    CUSTOM_ALL_FIELDS = [
        "GRAMMARLY_CLIENT_ID",
        "GRAMMARLY_CLIENT_SECRET",
        "GRAMMARLY_ACCESS_TOKEN",
        "GRAMMARLY_TOKEN_EXPIRES_AT",
        "GRAMMARLY_BASE_URL",
    ]
    CUSTOM_LOGIN_PROMPTS = [
        ("GRAMMARLY_CLIENT_ID", "Grammarly Client ID", False),
        ("GRAMMARLY_CLIENT_SECRET", "Grammarly Client Secret", True),
    ]
    CUSTOM_EPHEMERAL_FIELDS = [
        "GRAMMARLY_ACCESS_TOKEN",
        "GRAMMARLY_TOKEN_EXPIRES_AT",
    ]
    CUSTOM_SENSITIVE_FIELDS = [
        "GRAMMARLY_CLIENT_SECRET",
        "GRAMMARLY_ACCESS_TOKEN",
    ]
    ADDITIONAL_AUTH_FIELDS = ("GRAMMARLY_COOKIES",)
    ADDITIONAL_SENSITIVE_AUTH_FIELDS = ("GRAMMARLY_COOKIES",)

    LOGIN_INSTRUCTIONS = (
        "Get Grammarly API credentials from https://developer.grammarly.com/ "
        "and paste the OAuth client credentials below."
    )

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )
        self._cookies_file = Path.home() / ".grammarly_cookies"

    @property
    def client_id(self) -> Optional[str]:
        """Get Grammarly OAuth client ID."""
        return self._get("GRAMMARLY_CLIENT_ID")

    @property
    def client_secret(self) -> Optional[str]:
        """Get Grammarly OAuth client secret."""
        return self._get("GRAMMARLY_CLIENT_SECRET")

    @property
    def access_token(self) -> Optional[str]:
        """Get Grammarly access token."""
        return self._get("GRAMMARLY_ACCESS_TOKEN")

    @property
    def token_expires_at(self) -> Optional[str]:
        """Get token expiration timestamp."""
        return self._get("GRAMMARLY_TOKEN_EXPIRES_AT")

    @property
    def base_url(self) -> str:
        """Get Grammarly API base URL."""
        return self._get("GRAMMARLY_BASE_URL") or self.DEFAULT_BASE_URL

    @property
    def auth_url(self) -> str:
        """Get Grammarly OAuth token endpoint."""
        return "https://auth.grammarly.com/v4/api/oauth2/token"

    def has_credentials(self) -> bool:
        """Check only the plagiarism OAuth credential path.

        The shared BaseConfig ORs browser-session state into this check for
        multi-auth CLIs. Grammarly's `custom` path needs stricter semantics so
        auth status does not misreport docs cookies as plagiarism credentials.
        """
        return self.has_api_credentials()

    def has_api_credentials(self) -> bool:
        """Check whether the plagiarism OAuth client credentials are present."""
        return bool(self.client_id and self.client_secret)

    def save_tokens(self, access_token: str, expires_at: str):
        """Save OAuth tokens to the active profile."""
        self._set("GRAMMARLY_ACCESS_TOKEN", access_token)
        self._set("GRAMMARLY_TOKEN_EXPIRES_AT", expires_at)

    def clear_credentials(self):
        """Clear Grammarly credentials and docs cookies."""
        super().clear_credentials()
        self.clear_cookies()

    @property
    def cookies(self) -> Optional[str]:
        """Get Grammarly session cookies for docs API."""
        cookies = self._get("GRAMMARLY_COOKIES")
        if cookies:
            return cookies
        if self._cookies_file.exists():
            return self._cookies_file.read_text().strip()
        return None

    @property
    def csrf_token(self) -> Optional[str]:
        """Extract CSRF token from cookies."""
        cookies = self.cookies
        if not cookies:
            return None
        match = re.search(r"csrf[-_]token=([^;]+)", cookies)
        return match.group(1) if match else None

    def has_saved_session(self) -> bool:
        """Return whether docs cookies are available for the active profile."""
        return bool(self.cookies)

    def has_cookies(self) -> bool:
        """Check if session cookies are available."""
        return self.has_saved_session()

    def save_cookies(self, cookies: str):
        """Save docs cookies to the active auth profile."""
        self._set("GRAMMARLY_COOKIES", cookies.strip())

    def clear_cookies(self):
        """Clear saved cookies."""
        if self._cookies_file.exists():
            self._cookies_file.unlink()
        self._clear("GRAMMARLY_COOKIES")

    def clear_session(self):
        """Clear the docs cookie-backed browser session."""
        self.clear_cookies()
        super().clear_session()

    def get_browser(self):
        """Return the docs browser-session adapter for shared auth hooks."""
        from .browser import GrammarlyCookieBrowserSession

        return GrammarlyCookieBrowserSession(self)

    def test_connection(self) -> Optional[dict]:
        """Verify OAuth client credentials by obtaining an access token."""
        from .client import ClientError, GrammarlyClient
        try:
            GrammarlyClient(config=self).obtain_access_token()
            return {"api_test": "passed"}
        except ClientError as e:
            return {"api_test": f"failed: {e}"}


_configs: dict = {}


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create a config instance for the given profile."""
    key = (profile or "_default", os.environ.get("XDG_DATA_HOME"), os.environ.get("HOME"))
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]


def _reset_config():
    """Reset cached config instances for tests."""
    global _configs
    _configs = {}
