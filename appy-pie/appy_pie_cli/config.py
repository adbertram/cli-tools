"""Configuration management for AppyPie CLI (browser automation)."""

from typing import Optional

from cli_tools_shared.http_session import BrowserAuthState
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for AppyPie — extends BaseConfig for shared auth/profile support."""

    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://www.appy-pie.com/"
    DIST_NAME = "appy-pie-cli"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def get_browser(self):
        """Return the BrowserAutomation subclass for browser session authentication."""
        from .browser import AppyPieBrowser
        return AppyPieBrowser(self)

    def test_connection(self) -> dict:
        """Validate that a saved browser session exists for this profile."""
        BrowserAuthState.from_config(self)
        return {"api_test": "passed"}

    @property
    def storage_dir(self):
        """Profile-aware storage directory for runtime data."""
        return self.get_profile_data_dir()


_config: Optional[Config] = None


def get_config(profile=None) -> Config:
    """Get or create the config instance."""
    global _config
    if _config is None or profile is not None:
        _config = Config(profile=profile)
    return _config
