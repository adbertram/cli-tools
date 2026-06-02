"""Configuration management for Atlassian CLI (browser automation)."""

from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for Atlassian — extends BaseConfig for shared auth/profile support."""

    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://www.flexoffers.com/affiliate-programs/atlassian-affiliate-program/"
    DIST_NAME = "atlassian-cli"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def get_browser(self):
        """Return the BrowserAutomation subclass for browser session authentication."""
        from .browser import AtlassianBrowser
        return AtlassianBrowser(self)

    def test_connection(self) -> dict:
        """Validate the saved browser session for the configured host."""
        from urllib.parse import urlparse

        from cli_tools_shared.http_session import BrowserAuthState

        hostname = urlparse(self.base_url).hostname
        if not hostname:
            raise ValueError(f"BASE_URL does not contain a hostname: {self.base_url}")
        BrowserAuthState.from_config(self).cookies_for_host(
            hostname,
            allowed_domains=(hostname,),
        )
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
