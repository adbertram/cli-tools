"""Configuration management for Crowdgen CLI (browser automation).

Uses BaseConfig from cli_tools_shared for profile-aware env loading.
Browser automation lives in browser.py.
"""

from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.http_session import BrowserAuthState


class Config(BaseConfig):
    """Configuration for Crowdgen — extends BaseConfig for shared auth/profile support."""

    DIST_NAME = "crowdgen-cli"

    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://app.crowdgen.com"
    # CrowdGen's worker frontend talks to a separate API host; the deployed
    # bundle (main.b5c37aa5.js) resolves it from REACT_APP_BACKEND_URL.
    API_BASE_URL = "https://api.crowdgen.com"

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
        from .browser import CrowdgenBrowser
        return CrowdgenBrowser(self)

    def test_connection(self) -> dict:
        """Live check used by `auth status` / `auth test`.

        Mirrors the sibling browser CLIs: verify the saved browser profile
        actually carries CrowdGen session cookies for app.crowdgen.com.
        """
        BrowserAuthState.from_config(self).cookies_for_host(
            "app.crowdgen.com",
            allowed_domains=("crowdgen.com",),
        )
        return {"api_test": "passed"}


# Singleton pattern for config (per profile)
_configs: dict = {}


def get_config(profile=None) -> Config:
    """Get or create config instance for a profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
