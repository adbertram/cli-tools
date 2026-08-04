"""Configuration management for Vinted CLI."""

import re
import subprocess
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ClientError

_UA_TEMPLATE = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/{version} Safari/537.36"
)

_derived_browser_user_agent: Optional[str] = None


def derive_browser_user_agent() -> str:
    """Return the real-Chrome user agent to present headed AND headless.

    Cloudflare binds the `cf_clearance` cookie to the user agent that earned it.
    Headless Chrome sends `HeadlessChrome/<v>` by default, which does not match
    the headed login and re-triggers the challenge. The version comes from the
    installed Chrome, so a Chrome update does not make the value stale.
    """
    global _derived_browser_user_agent
    if _derived_browser_user_agent is not None:
        return _derived_browser_user_agent

    from cli_tools_shared.browser import driver

    result = subprocess.run(
        [driver._chrome_binary(), "--version"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    match = re.search(r"(\d+\.\d+\.\d+\.\d+)", result.stdout)
    if not match:
        raise ClientError(
            f"Could not read the installed Chrome version from: {result.stdout!r}"
        )
    _derived_browser_user_agent = _UA_TEMPLATE.format(version=match.group(1))
    return _derived_browser_user_agent


class Config(BaseConfig):
    DIST_NAME = "vinted-cli"
    # Vinted needs no account. The session exists only to hold the Cloudflare
    # clearance that lets the catalog API answer at all.
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://www.vinted.com"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def headless(self) -> bool:
        """Run headless unless the user asks for a window."""
        return (self._get("HEADLESS") or "true").lower() == "true"

    @property
    def browser_user_agent(self) -> str:
        """User agent applied to headed AND headless Chrome.

        The shared engine reads this attribute and passes it to Chrome as
        `--user-agent`. Without it, headless Chrome leaks the `HeadlessChrome`
        token and Cloudflare rejects the saved clearance.
        """
        return self._get("BROWSER_USER_AGENT") or derive_browser_user_agent()

    def get_browser(self):
        """Return the browser automation instance for this profile.

        Each Vinted country site is a separate host with its own Cloudflare
        clearance, so the session URLs follow BASE_URL. `browser.py` stays
        declarative, which the shared architecture rules require.
        """
        from .browser import VintedBrowser

        browser = VintedBrowser(self)
        home = f"{self.base_url.rstrip('/')}/"
        browser.LOGIN_URL = home
        browser.AUTH_CHECK_URL = home
        return browser

    def test_connection(self) -> dict:
        """Validate that the saved session reaches the Vinted catalog."""
        from .client import VintedClient

        try:
            VintedClient(config=self).search_listings("lego", limit=1)
            return {"api_test": "passed"}
        except ClientError as exc:
            return {"api_test": f"failed: {exc}"}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
