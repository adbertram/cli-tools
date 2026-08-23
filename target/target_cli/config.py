"""Configuration management for Target CLI (browser automation).

Uses BaseConfig from cli_tools_shared for profile-aware env loading.
Browser automation lives in browser.py.
"""

from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for Target — extends BaseConfig for shared auth/profile support."""

    DIST_NAME = "target-cli"

    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://www.target.com"

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
    def store_id(self) -> str:
        """Default Target store id for pricing/inventory (overridable via STORE_ID)."""
        return self._get("STORE_ID") or "108"

    @property
    def zip(self) -> str:
        """Default zip for geo context (overridable via ZIP)."""
        return self._get("ZIP") or "47710"

    def get_browser(self):
        """Return the browser used for account login + cart/checkout."""
        return TargetSessionBrowser(self)

    def test_connection(self) -> dict:
        browser = self.get_browser()
        return browser.test_session()


class TargetSessionBrowser:
    """Login orchestration: account sign-in AND redsky read-session capture.

    Composition wrapper around the declarative ``TargetBrowser`` (browser.py):
    it adds a ``login()`` that runs the shared account login and then primes the
    redsky fast-search session, so a single ``target auth login`` sets up
    everything. Lives in config.py (not browser.py) so the ``BrowserAutomation``
    subclass stays declarative per the lean-CLI architecture rules; all other
    calls delegate to the wrapped browser.
    """

    def __init__(self, config):
        from .browser import TargetBrowser
        self._config = config
        self._browser = TargetBrowser(config)

    def __getattr__(self, name):
        # Delegate get_page / cookie_list / close / is_authenticated / etc.
        return getattr(self._browser, name)

    def login(self, force: bool = False) -> dict:
        result = self._browser.login(force=force)
        if not result.get("success"):
            return result
        from .prime import prime_redsky

        try:
            count = prime_redsky(self._config)
        except Exception as exc:
            result["success"] = False
            result["message"] = (
                f"Account login succeeded (cart/checkout ready), but fast-search prime "
                f"failed: {exc}. Run `target session refresh` to capture it."
            )
            return result
        result["message"] = (
            f"Account session saved and fast-search session captured ({count} results)."
        )
        return result


# Singleton pattern for config (per profile)
_configs: dict = {}


def get_config(profile=None) -> Config:
    """Get or create config instance for a profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
