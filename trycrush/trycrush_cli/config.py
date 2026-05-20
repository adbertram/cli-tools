"""Configuration management for Trycrush CLI (browser automation)."""

from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for Trycrush — extends BaseConfig for shared auth/profile support."""

    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://trycrush.ai"
    DIST_NAME = "trycrush-cli"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def get_browser(self):
        """Return the BrowserAutomation subclass for browser session authentication."""
        from .browser import TrycrushBrowser
        return TrycrushBrowser(self)

    def test_connection(self) -> dict:
        """Test connection by checking saved browser session authentication."""
        browser = self.get_browser()
        try:
            if browser.is_authenticated():
                return {"api_test": "passed", "browser_session": "authenticated"}
            return {
                "api_test": "failed: not authenticated",
                "browser_session": "not authenticated",
            }
        except Exception as exc:
            return {"api_test": f"failed: {exc}"}
        finally:
            try:
                browser.close()
            except Exception:
                pass

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
