"""Configuration management for MuseChat CLI (browser automation).

Uses BaseConfig from cli_tools_shared for profile-aware env loading.
Browser automation lives in browser.py.
"""

from typing import Optional

from cli_tools_shared.config import BaseConfig, config_getter, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for MuseChat — extends BaseConfig for shared auth/profile support."""

    DIST_NAME = "muse-chat-cli"

    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://muse.ai"

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
        from .browser import MuseChatBrowser
        return MuseChatBrowser(self)

    def test_connection(self) -> dict:
        """Perform the live browser-session check used by ``auth test``."""
        return self.get_browser().test_session()


get_config = config_getter(Config)
