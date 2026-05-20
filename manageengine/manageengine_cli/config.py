"""Configuration management for Manageengine CLI (browser automation)."""

from typing import Optional

from cli_tools_shared.http_session import BrowserAuthState
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for Manageengine — extends BaseConfig for shared auth/profile support."""

    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://www.manageengine.com/affiliate/signup.html"
    DIST_NAME = "manageengine-cli"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def get_browser(self):
        """Return the BrowserAutomation subclass for browser session authentication."""
        from .browser import ManageengineBrowser
        return ManageengineBrowser(self)

    def test_connection(self) -> dict:
        """Validate that a saved browser session exists for this profile."""
        BrowserAuthState.from_config(self)
        return {"api_test": "passed"}

    @property
    def storage_dir(self):
        """Profile-aware storage directory for runtime data."""
        return self.get_profile_data_dir()


def get_config(profile=None) -> Config:
    """Create a config instance for the requested profile."""
    return Config(profile=profile)
