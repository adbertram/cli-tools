"""Configuration management for Microworkers CLI (browser automation).

Uses BaseConfig from cli_tools_shared for profile-aware env loading.
Browser automation lives in browser.py.
"""

from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.http_session import BrowserAuthState


class Config(BaseConfig):
    """Configuration for Microworkers — extends BaseConfig for shared auth/profile support."""

    DIST_NAME = "microworkers-cli"

    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://www.microworkers.com"

    # Root (non-auth) config fields this CLI accepts in its .env files. The
    # listing-pacing knobs below must be whitelisted so `config set` and the
    # .env loader accept them (see the issue #52 pacing fix).
    ROOT_CONFIG_FIELDS = ("LIST_PAGE_DELAY_SECONDS", "LIST_PAGE_DELAY_JITTER")

    DEFAULT_LIST_PAGE_DELAY_SECONDS = 4.0
    DEFAULT_LIST_PAGE_DELAY_JITTER = 0.5

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def headless(self) -> bool:
        val = self._get("HEADLESS")
        return val is None or val.lower() == "true"

    @property
    def list_page_delay_seconds(self) -> float:
        """Base seconds between consecutive /jobs.php listing page loads.

        A malformed value silently falls back to the safe default so a bad
        config never disables pacing (and risks the account ban again).
        """
        val = self._get("LIST_PAGE_DELAY_SECONDS")
        if val is None:
            return self.DEFAULT_LIST_PAGE_DELAY_SECONDS
        try:
            return float(val)
        except ValueError:
            return self.DEFAULT_LIST_PAGE_DELAY_SECONDS

    @property
    def list_page_delay_jitter(self) -> float:
        """Fractional jitter applied to the listing page delay.

        The effective per-page pause is drawn from
        ``base * [1 - jitter, 1 + jitter]`` and clamped in the client. A
        malformed value falls back to the safe default.
        """
        val = self._get("LIST_PAGE_DELAY_JITTER")
        if val is None:
            return self.DEFAULT_LIST_PAGE_DELAY_JITTER
        try:
            return float(val)
        except ValueError:
            return self.DEFAULT_LIST_PAGE_DELAY_JITTER

    def get_browser(self):
        """Return the BrowserAutomation subclass for this CLI."""
        from .browser import MicroworkersBrowser
        return MicroworkersBrowser(self)

    def test_connection(self) -> dict:
        BrowserAuthState.from_config(self).cookies_for_host(
            "www.microworkers.com",
            allowed_domains=("microworkers.com",),
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
