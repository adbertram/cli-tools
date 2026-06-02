"""Configuration management for Brick Owl CLI.

Brick Owl uses a simple API key for REST API auth and
browser automation (via shared BrowserAutomation module) for
features not available via API (messages, refunds, coupons).
"""
from pathlib import Path

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Brick Owl CLI configuration.

    Uses API_KEY credential type. Browser automation is handled by
    the shared BrowserAutomation module via get_browser().
    """

    DIST_NAME = "brickowl-cli"

    CREDENTIAL_TYPES = [CredentialType.API_KEY, CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://api.brickowl.com/v1"
    ADDITIONAL_AUTH_FIELDS = ("USERNAME", "PASSWORD")
    ADDITIONAL_SENSITIVE_AUTH_FIELDS = ("USERNAME", "PASSWORD")

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def storage_dir(self) -> Path:
        """Get storage directory for the active profile (used by @cached decorator)."""
        return self.get_profile_data_dir()

    @property
    def headless(self) -> bool:
        """Whether to run browser in headless mode."""
        import os
        return os.getenv("HEADLESS", "true").lower() == "true"

    def get_browser(self):
        """Return BrickOwlBrowser instance for browser-based automation."""
        from .browser import BrickOwlBrowser
        return BrickOwlBrowser(self)

    def has_api_credentials(self) -> bool:
        """Check if API key credential is configured (ignores browser session)."""
        return bool(self.api_key)


_configs = {}


def get_config(profile=None) -> Config:
    """Get or create a config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
