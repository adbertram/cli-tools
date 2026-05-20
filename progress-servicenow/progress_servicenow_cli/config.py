"""Configuration management for ProgressServicenow CLI (browser automation)."""

from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for ProgressServicenow — extends BaseConfig for shared auth/profile support."""

    DIST_NAME = "progress-servicenow-cli"

    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://progress1.service-now.com/esc"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def get_browser(self):
        """Return browser automation instance for browser session authentication.

        Returns a cached instance so the credential gate and command handlers
        share the same BrowserAutomation-managed browser session within a
        single process.
        """
        if not hasattr(self, '_browser_instance') or self._browser_instance is None:
            from .browser import ProgressServiceNowBrowser

            self._browser_instance = ProgressServiceNowBrowser(self)
        return self._browser_instance

    def test_connection(self):
        """Test connection by checking browser session authentication."""
        browser = self.get_browser()
        try:
            result = browser.is_authenticated()
            if result:
                return {"api_test": "passed", "browser_session": "authenticated"}
            return {"api_test": "failed: not authenticated", "browser_session": "not authenticated"}
        except Exception as e:
            return {"api_test": f"failed: {e}"}
        finally:
            try:
                browser.close()
            except Exception:
                pass

    @property
    def storage_dir(self) -> Path:
        """Profile-aware storage directory for runtime data."""
        return self.get_profile_data_dir()


_config: Optional[Config] = None


def get_config(profile=None) -> Config:
    """Get or create the config instance."""
    global _config
    if _config is None or profile is not None:
        _config = Config(profile=profile)
    return _config
