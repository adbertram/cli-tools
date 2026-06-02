"""Configuration management for Facebook CLI."""
from pathlib import Path

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration manager for Facebook CLI."""

    DIST_NAME = "facebook-cli"

    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://www.facebook.com"
    ADDITIONAL_AUTH_FIELDS = ("USERNAME", "PASSWORD", "AUTH_COOKIES_JSON")
    ADDITIONAL_SENSITIVE_AUTH_FIELDS = ("USERNAME", "PASSWORD", "AUTH_COOKIES_JSON")

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def storage_dir(self) -> Path:
        """Get profile data directory used by shared cache helpers."""
        return self.get_profile_data_dir()

    @property
    def cache_dir(self) -> Path:
        """Get the per-profile cache directory."""
        d = self.storage_dir / "cache"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get_browser(self):
        """Return browser service for Facebook browser-based auth."""
        from .browser import FacebookBrowser
        return FacebookBrowser(self)

    def has_credentials(self) -> bool:
        """Check if browser session exists."""
        return self.get_browser().has_session()

    def test_connection(self):
        """Test if browser session is active."""
        browser = self.get_browser()
        if not browser.has_session():
            return {"api_test": "failed: no active browser session"}
        try:
            result = browser.test_session()
            if result.get("authenticated"):
                return {"api_test": "passed (browser session active)"}
            return {"api_test": f"failed: {result.get('error', 'not authenticated')}"}
        except Exception as e:
            return {"api_test": f"failed: {e}"}


_configs = {}


def get_config(profile=None):
    """Get or create a config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
