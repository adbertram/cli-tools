"""Configuration management for Apple CLI."""

from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for Apple purchase history access."""

    DIST_NAME = "apple-cli"

    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://reportaproblem.apple.com"

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def storage_dir(self) -> Path:
        """Profile-aware storage directory for runtime data."""
        return self.get_profile_data_dir()

    @property
    def headless(self) -> bool:
        val = self._get("HEADLESS")
        if val is None:
            return True
        return val.lower() == "true"

    @property
    def request_context_path(self) -> Path:
        """Persisted purchase-search replay context captured by auth login."""
        return self.get_profile_data_dir() / "apple-reportaproblem-request-context.json"

    def get_browser(self):
        """Return the BrowserAutomation subclass for this CLI."""
        from .browser import AppleBrowser
        return AppleBrowser(self)


# Singleton pattern for config (per profile)
_configs: dict = {}


def get_config(profile=None) -> Config:
    """Get or create config instance for a profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
