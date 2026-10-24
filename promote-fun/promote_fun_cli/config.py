"""Configuration management for PromoteFun CLI (browser automation).

Uses BaseConfig from cli_tools_shared for profile-aware env loading.
Browser automation lives in browser.py.
"""

from typing import Optional

from cli_tools_shared.config import BaseConfig, config_for, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for PromoteFun — extends BaseConfig for shared auth/profile support."""

    DIST_NAME = "promote-fun-cli"

    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://www.promote.fun"

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def test_connection(self):
        from .client import PromoteFunClient
        client = PromoteFunClient(config=self)
        try:
            client.account()
            return {'api_test': 'passed'}
        finally:
            client.close()

    @property
    def headless(self) -> bool:
        val = self._get("HEADLESS")
        return val is None or val.lower() == "true"

    def get_browser(self):
        """Return the BrowserAutomation subclass for this CLI."""
        from .browser import PromoteFunBrowser
        return PromoteFunBrowser(self)


# Singleton pattern for config (per profile)
_configs: dict = {}


def get_config(profile=None) -> Config:
    """Get or create config instance for a profile."""
    return config_for(Config, profile, _configs)
