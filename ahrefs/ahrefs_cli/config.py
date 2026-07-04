"""Configuration management for Ahrefs CLI.

Handles environment variables, credentials, and browser session persistence.
All configuration is stored in .env file and browser data directory.
"""
import re
import shutil
import subprocess
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


# Real-Chrome fallback UA matching the installed Chrome, with NO "Headless"
# token, presented identically headed and headless. Used only if the installed
# Chrome version cannot be read at runtime; the version here may drift from the
# actual installed Chrome, so the runtime derivation below is preferred.
_FALLBACK_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.7827.201 Safari/537.36"
)

_UA_TEMPLATE = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/{version} Safari/537.36"
)

_derived_browser_user_agent: Optional[str] = None


def _installed_chrome_version() -> Optional[str]:
    """Return the installed Chrome version string (e.g. '149.0.7827.201').

    Locates Chrome via the shared browser-harness resolver, then reads its
    version with ``--version`` (no window, no CDP). Returns None if Chrome
    cannot be located or its version parsed.
    """
    from cli_tools_shared.browser import driver

    chrome = driver._chrome_binary()
    result = subprocess.run(
        [chrome, "--version"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    match = re.search(r"(\d+\.\d+\.\d+\.\d+)", result.stdout)
    if not match:
        return None
    return match.group(1)


def derive_browser_user_agent() -> str:
    """Derive the real-Chrome UA to present headed AND headless.

    Headless Chrome sends ``HeadlessChrome/<v>`` by default, which does not
    match the UA that the profile's Cloudflare ``cf_clearance`` cookie is bound
    to (minted during the headed login). We therefore build a UA that carries
    the installed Chrome's full version with NO "Headless" token, so the same
    value is presented headed and headless. Derived once and cached; falls back
    to the validated literal if the installed version cannot be read.
    """
    global _derived_browser_user_agent
    if _derived_browser_user_agent is not None:
        return _derived_browser_user_agent
    try:
        version = _installed_chrome_version()
    except Exception:
        version = None
    if version:
        _derived_browser_user_agent = _UA_TEMPLATE.format(version=version)
    else:
        _derived_browser_user_agent = _FALLBACK_BROWSER_USER_AGENT
    return _derived_browser_user_agent


class Config(BaseConfig):

    DIST_NAME = "ahrefs-cli"
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    BROWSER_SESSION_REQUIRES_API_TEST = True
    DEFAULT_BASE_URL = "https://app.ahrefs.com"
    ADDITIONAL_AUTH_FIELDS = ("USERNAME", "PASSWORD")
    ADDITIONAL_SENSITIVE_AUTH_FIELDS = ("USERNAME", "PASSWORD")

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    # Browser-specific properties
    @property
    def headless(self) -> bool:
        """Get headless browser mode setting."""
        return (self._get("HEADLESS") or "false").lower() == "true"

    @property
    def browser_user_agent(self) -> str:
        """User-Agent override applied to headed AND headless Chrome.

        The shared engine (`BrowserAutomation._browser_user_agent()`) picks this
        up via ``hasattr`` and passes it to Chrome as ``--user-agent``. Without
        it, headless Chrome sends ``HeadlessChrome/<v>``, which does not match
        the UA that the profile's Cloudflare ``cf_clearance`` cookie was bound
        to during the headed login, so data commands get walled. A ``.env``
        ``BROWSER_USER_AGENT`` value overrides the auto-derived UA.
        """
        override = self._get("BROWSER_USER_AGENT")
        if override:
            return override
        return derive_browser_user_agent()

    @property
    def auth_indicator_selector(self) -> Optional[str]:
        """CSS selector that should exist when logged in.

        Used by `auth test` to verify authentication.
        """
        return self._get("AUTH_INDICATOR_SELECTOR")

    @property
    def login_redirect_pattern(self) -> Optional[str]:
        """URL pattern that indicates redirect to login page.

        Used by `auth test` to detect if the session was rejected.
        """
        return self._get("LOGIN_REDIRECT_PATTERN")

    # Legacy compatibility - storage_dir for browser.py profile_path
    def clear_session(self):
        """Clear saved session data including legacy directories."""
        # Clear profile-aware session data
        super().clear_session()

        # Also clear legacy directories if they exist
        tool_dir = self.tool_dir
        legacy_browser = tool_dir / ".browser-data"
        if legacy_browser.exists():
            shutil.rmtree(legacy_browser)
        legacy_storage = tool_dir / ".storage"
        if legacy_storage.exists():
            shutil.rmtree(legacy_storage)

    def get_browser(self):
        """Return browser automation instance for browser-based authentication."""
        from .browser import AhrefsBrowser
        return AhrefsBrowser(self)

    def clear_all(self):
        """Clear all credentials and session data."""
        self.clear_credentials()
        self.clear_session()


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
