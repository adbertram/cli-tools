"""Configuration management for Techsmith CLI (browser automation)."""

from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for Techsmith — extends BaseConfig for shared auth/profile support."""

    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://www.techsmith.com/resources/affiliate-partners/"
    DIST_NAME = "techsmith-cli"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def get_browser(self):
        """Return the BrowserAutomation subclass for browser session authentication."""
        from .browser import TechsmithBrowser
        return TechsmithBrowser(self)

    def test_connection(self) -> Optional[dict]:
        """Verify the saved browser session can still open the site."""
        browser = self.get_browser()
        try:
            result = browser.test_session()
        finally:
            browser.close()
        if result.get("authenticated"):
            return {"api_test": "passed"}
        return {"api_test": f"failed: {result.get('message', 'browser session not authenticated')}"}

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
