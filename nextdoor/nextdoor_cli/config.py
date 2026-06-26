"""Configuration management for Nextdoor CLI (browser automation).

Uses BaseConfig from cli_tools_shared for profile-aware env loading and the
persistent Chromium user-data-dir session model. Browser automation lives in
browser.py; the persistent profile is the single source of truth for the
authenticated session, so this config does NOT override the inherited
browser-session credential checks.
"""

from pathlib import Path

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType

NEXTDOOR_HOST = "nextdoor.com"
NEXTDOOR_ORIGIN = f"https://{NEXTDOOR_HOST}"
NEXTDOOR_ALLOWED_DOMAINS = (NEXTDOOR_HOST,)


class Config(BaseConfig):
    DIST_NAME = "nextdoor-cli"
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = f"{NEXTDOOR_ORIGIN}/api/gql"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def storage_dir(self) -> Path:
        """Profile-aware storage directory for runtime state."""
        return self.get_profile_data_dir()

    @property
    def headless(self) -> bool:
        val = self._get("HEADLESS")
        return val is None or val.lower() == "true"

    def get_browser(self):
        """Return the browser automation instance for this config."""
        from .browser import NextdoorBrowser
        return NextdoorBrowser(self)

    def test_connection(self) -> dict:
        """Validate the saved session by making a real authenticated API call.

        Cookie presence alone is not proof of authentication — Nextdoor sets
        session cookies for logged-out visitors too. This makes a live ``getMe``
        GraphQL call, which fails loudly (no fallback) when the session is not
        authenticated server-side, so 'auth test' surfaces the real problem.
        """
        from .client import NextdoorClient

        client = NextdoorClient(config=self)
        try:
            user = client.get_me()
        finally:
            client.close()
        return {"api_test": "passed", "user_id": user.get("id")}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
