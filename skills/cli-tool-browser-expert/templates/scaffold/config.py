"""Configuration management for {{ServiceName}} CLI.

Uses BaseConfig from cli_tools_common for profile-aware env loading.
Browser automation lives in browser.py.
"""

from pathlib import Path
from typing import Optional

from cli_tools_common import BaseConfig
from cli_tools_common.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for {{ServiceName}} CLI."""

    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    # For dual auth (API + browser), use:
    # CREDENTIAL_TYPES = [CredentialType.OAUTH, CredentialType.BROWSER_SESSION]

    DEFAULT_BASE_URL = "https://{{domain}}"

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=Path(__file__).resolve().parent.parent,
            profile=profile,
        )

    @property
    def storage_dir(self) -> Path:
        return self.get_profile_data_dir()

    @property
    def headless(self) -> bool:
        """Whether to run browser in headless mode (default: True)."""
        val = self._get("HEADLESS")
        return val is None or val.lower() == "true"

    def get_browser(self):
        """Return browser automation instance.

        Uses lazy import to avoid circular imports.
        AuthVerifier calls this automatically during auth status/test.
        """
        from .browser import {{ServiceName}}Browser
        return {{ServiceName}}Browser(self)


# Module-level singleton factory
_configs = {}


def get_config(profile=None) -> Config:
    """Get or create config instance for a profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
