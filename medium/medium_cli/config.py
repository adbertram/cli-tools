"""Configuration management for Medium CLI."""

from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for browser-based Medium draft creation."""

    DIST_NAME = "medium-cli"
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://medium.com"
    DEFAULT_BROWSER_USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    )
    DEFAULT_BROWSER_WINDOW_SIZE = "1280,900"

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def storage_dir(self) -> Path:
        """Profile-aware runtime data directory."""
        return self.get_profile_data_dir()

    @property
    def headless(self) -> bool:
        value = self._get("HEADLESS")
        if value is None:
            return True
        return value.lower() == "true"

    @property
    def browser_user_agent(self) -> str:
        return self._get("BROWSER_USER_AGENT") or self.DEFAULT_BROWSER_USER_AGENT

    @property
    def browser_window_size(self) -> str:
        return self._get("BROWSER_WINDOW_SIZE") or self.DEFAULT_BROWSER_WINDOW_SIZE

    def get_browser(self):
        """Return the BrowserAutomation subclass for this CLI."""
        from .browser import MediumBrowser

        return MediumBrowser(self)


_configs: dict[str, Config] = {}


def get_config(profile: Optional[str] = None) -> Config:
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
