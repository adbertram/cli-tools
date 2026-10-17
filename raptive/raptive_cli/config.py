"""Configuration management for Raptive CLI.

Extends BaseConfig from cli_tools_shared for profile-aware env loading,
credential management, and browser session persistence.
"""
from typing import Optional

from cli_tools_shared.browser.user_agent import derive_real_chrome_user_agent
from cli_tools_shared.config import BaseConfig, config_for, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for Raptive CLI."""

    DIST_NAME = "raptive"

    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://dashboard.raptive.com"
    ADDITIONAL_AUTH_FIELDS = ("USERNAME", "PASSWORD")
    ADDITIONAL_SENSITIVE_AUTH_FIELDS = ("USERNAME", "PASSWORD")
    # A saved token alone is not proof: AWS WAF can still reject every API
    # call, so `auth status` must pass the live publisher-API test.
    BROWSER_SESSION_REQUIRES_API_TEST = True

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def api_base_url(self) -> str:
        """Get Raptive Publisher API base URL."""
        return self._get("API_BASE_URL") or "https://publisher-api.raptive.com"

    @property
    def site_id(self) -> Optional[str]:
        """Get the Raptive site ID."""
        return self._get("SITE_ID")

    @property
    def headless(self) -> bool:
        """Get headless browser mode setting."""
        return (self._get("HEADLESS") or "true").lower() == "true"

    @property
    def browser_user_agent(self) -> str:
        """Present the installed real-Chrome UA headed and headless.

        The dashboard's AWS WAF check rejects the default HeadlessChrome UA
        ("We couldn't verify your browser session").
        """
        return self._get("BROWSER_USER_AGENT") or derive_real_chrome_user_agent()

    @property
    def login_redirect_pattern(self) -> Optional[str]:
        """URL pattern that indicates redirect to login page."""
        return self._get("LOGIN_REDIRECT_PATTERN")

    def get_browser(self):
        """Return browser service instance for browser-based authentication."""
        from .browser import RaptiveBrowser
        return RaptiveBrowser(self)


_configs = {}


def get_config(profile=None) -> Config:
    """Get a Config instance for the given profile."""
    return config_for(Config, profile, _configs)
