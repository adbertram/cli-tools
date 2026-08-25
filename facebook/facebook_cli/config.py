"""Configuration management for Facebook CLI."""
from pathlib import Path

from cli_tools_shared.browser.user_agent import derive_real_chrome_user_agent
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration manager for Facebook CLI."""

    DIST_NAME = "facebook-cli"

    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://www.facebook.com"
    # AUTH_COOKIES_JSON is deliberately absent. A stored cookie snapshot is a
    # second source of truth for the session, and Facebook rotates the ``xs``
    # cookie inside the browser profile whenever it re-issues the session: the
    # frozen copy then keeps a retired value and every HTTP read comes back as
    # the logged-out variant of the page. The persistent Chromium profile is the
    # only session store this CLI reads (see FacebookClient._facebook_http_client).
    ADDITIONAL_AUTH_FIELDS = ("USERNAME", "PASSWORD")
    ADDITIONAL_SENSITIVE_AUTH_FIELDS = ("USERNAME", "PASSWORD")

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def browser_user_agent(self) -> str:
        """Use the installed real-Chrome UA for headed and headless sessions."""
        override = self._get("BROWSER_USER_AGENT")
        if override:
            return override
        return derive_real_chrome_user_agent()

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
