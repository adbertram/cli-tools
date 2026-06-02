"""Configuration management for Brickfreedom CLI.

Uses BaseConfig from cli_tools_shared for profile-aware env loading.
Browser automation lives in browser.py.
"""
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for Brickfreedom CLI."""

    DIST_NAME = "brickfreedom-cli"

    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://brickfreedom.com"

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def storage_dir(self) -> Path:
        return self.get_profile_data_dir()

    @property
    def headless(self) -> bool:
        val = self._get("HEADLESS")
        return val is None or val.lower() == "true"

    def get_browser(self):
        from .browser import BrickfreedomBrowser
        return BrickfreedomBrowser(self)


# Singleton pattern for config
_configs = {}


def get_config(profile=None) -> Config:
    """Get or create config instance for a profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
