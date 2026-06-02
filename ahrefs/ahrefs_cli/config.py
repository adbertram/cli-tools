"""Configuration management for Ahrefs CLI.

Handles environment variables, credentials, and browser session persistence.
All configuration is stored in .env file and browser data directory.
"""
import shutil
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):

    DIST_NAME = "ahrefs-cli"
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    BROWSER_SESSION_REQUIRES_API_TEST = True
    DEFAULT_BASE_URL = "https://app.ahrefs.com"
    ADDITIONAL_AUTH_FIELDS = ("USERNAME", "PASSWORD")
    ADDITIONAL_SENSITIVE_AUTH_FIELDS = ("USERNAME", "PASSWORD")

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    # Browser-specific properties
    @property
    def headless(self) -> bool:
        """Get headless browser mode setting."""
        return (self._get("HEADLESS") or "false").lower() == "true"

    @property
    def auth_indicator_selector(self) -> Optional[str]:
        """CSS selector that should exist when logged in.

        Used by `auth test` to verify authentication.
        """
        return self._get("AUTH_INDICATOR_SELECTOR")

    @property
    def login_redirect_pattern(self) -> Optional[str]:
        """URL pattern that indicates redirect to login page.

        Used by `auth test` to detect if the session was rejected.
        """
        return self._get("LOGIN_REDIRECT_PATTERN")

    # Legacy compatibility - storage_dir for browser.py profile_path
    @property
    def storage_dir(self) -> Path:
        """Get storage directory for the active profile (legacy compatibility)."""
        return self.get_profile_data_dir()

    def clear_session(self):
        """Clear saved session data including legacy directories."""
        # Clear profile-aware session data
        super().clear_session()

        # Also clear legacy directories if they exist
        tool_dir = self.tool_dir
        legacy_browser = tool_dir / ".browser-data"
        if legacy_browser.exists():
            shutil.rmtree(legacy_browser)
        legacy_storage = tool_dir / ".storage"
        if legacy_storage.exists():
            shutil.rmtree(legacy_storage)

    def get_browser(self):
        """Return browser automation instance for browser-based authentication."""
        from .browser import AhrefsBrowser
        return AhrefsBrowser(self)

    def clear_all(self):
        """Clear all credentials and session data."""
        self.clear_credentials()
        self.clear_session()


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
