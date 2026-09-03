"""Configuration management for Microworkers CLI (browser automation).

Uses BaseConfig from cli_tools_shared for profile-aware env loading.
Browser automation lives in browser.py.
"""

from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.http_session import BrowserAuthState


class Config(BaseConfig):
    """Configuration for Microworkers — extends BaseConfig for shared auth/profile support."""

    DIST_NAME = "microworkers-cli"

    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://www.microworkers.com"

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def headless(self) -> bool:
        val = self._get("HEADLESS")
        return val is None or val.lower() == "true"

    def get_browser(self):
        """Return the BrowserAutomation subclass for this CLI."""
        from .browser import MicroworkersBrowser
        return MicroworkersBrowser(self)

    def test_connection(self) -> dict:
        BrowserAuthState.from_config(self).cookies_for_host(
            "www.microworkers.com",
            allowed_domains=("microworkers.com",),
        )
        return {"api_test": "passed"}


# Singleton pattern for config (per profile)
_configs: dict = {}


def get_config(profile=None) -> Config:
    """Get or create config instance for a profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
