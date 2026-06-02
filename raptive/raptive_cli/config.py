"""Configuration management for Raptive CLI.

Extends BaseConfig from cli_tools_shared for profile-aware env loading,
credential management, and browser session persistence.
"""
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for Raptive CLI."""

    DIST_NAME = "raptive"

    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://dashboard.raptive.com"
    ADDITIONAL_AUTH_FIELDS = ("USERNAME", "PASSWORD")
    ADDITIONAL_SENSITIVE_AUTH_FIELDS = ("USERNAME", "PASSWORD")

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def api_base_url(self) -> str:
        """Get Raptive Publisher API base URL."""
        return self._get("API_BASE_URL") or "https://publisher-api.raptive.com"

    @property
    def site_id(self) -> Optional[str]:
        """Get the Raptive site ID."""
        return self._get("SITE_ID")

    @property
    def headless(self) -> bool:
        """Get headless browser mode setting."""
        return (self._get("HEADLESS") or "true").lower() == "true"

    @property
    def login_redirect_pattern(self) -> Optional[str]:
        """URL pattern that indicates redirect to login page."""
        return self._get("LOGIN_REDIRECT_PATTERN")

    @property
    def storage_dir(self) -> Path:
        """Storage directory for cache and profile data."""
        return self.get_profile_data_dir()

    def get_browser(self):
        """Return browser service instance for browser-based authentication."""
        from .browser import RaptiveBrowser
        return RaptiveBrowser(self)


def get_config(profile=None) -> Config:
    """Get a Config instance for the given profile."""
    return Config(profile=profile)
