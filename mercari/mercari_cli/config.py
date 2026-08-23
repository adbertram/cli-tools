"""Configuration management for Mercari CLI (browser automation).

Uses BaseConfig from cli_tools_shared for profile-aware env loading.
Browser automation lives in browser.py.
"""

from typing import Optional

from cli_tools_shared.browser.user_agent import derive_real_chrome_user_agent
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for Mercari — extends BaseConfig for shared auth/profile support."""

    DIST_NAME = "mercari-cli"

    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://www.mercari.com"

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
    def browser_user_agent(self) -> str:
        """Real-Chrome UA presented headed AND headless.

        mercari.com sits behind Cloudflare; the default ``HeadlessChrome/<v>``
        UA token gets walled and breaks the UA-bound ``cf_clearance`` cookie.
        A ``.env`` ``BROWSER_USER_AGENT`` value overrides the auto-derived UA.
        """
        override = self._get("BROWSER_USER_AGENT")
        if override:
            return override
        return derive_real_chrome_user_agent()

    def get_browser(self):
        """Return the BrowserAutomation subclass for this CLI."""
        from .browser import MercariBrowser
        return MercariBrowser(self)

    def test_connection(self) -> dict:
        """Live browser-session verification used by `mercari auth test`.

        Navigates the persistent session to the authenticated area and returns
        the shared browser session test result.
        """
        return self.get_browser().test_session()


# Singleton pattern for config (per profile)
_configs: dict = {}


def get_config(profile=None) -> Config:
    """Get or create config instance for a profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
