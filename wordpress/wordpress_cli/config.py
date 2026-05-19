"""Configuration management for Wordpress CLI."""
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):

    DIST_NAME = "wordpress-cli"
    CREDENTIAL_TYPES = [CredentialType.USERNAME_PASSWORD]
    DEFAULT_BASE_URL = "https://adamtheautomator.com/wp-json/wp/v2"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def _get(self, key):
        """Override to support WordPress-specific env var names.

        Maps PASSWORD -> APP_PASSWORD and BASE_URL -> URL-derived value
        for backwards compatibility with existing .env files.
        """
        val = super()._get(key)
        if val is not None:
            return val

        # Fall back: PASSWORD -> APP_PASSWORD
        if key == "PASSWORD":
            return super()._get("APP_PASSWORD")

        # Fall back: BASE_URL -> constructed from URL
        if key == "BASE_URL":
            url = super()._get("URL")
            if url:
                url = url.rstrip("/")
                if not url.endswith("/wp-json/wp/v2"):
                    url = f"{url}/wp-json/wp/v2"
                return url

        return None

    @property
    def app_password(self) -> Optional[str]:
        """Get WordPress Application Password."""
        return self._get("APP_PASSWORD") or self._get("PASSWORD")

    @property
    def url(self) -> Optional[str]:
        """Get WordPress site URL."""
        return super()._get("URL")

    def test_connection(self) -> bool:
        """Test WordPress API connectivity with a lightweight call."""
        import requests
        from requests.auth import HTTPBasicAuth

        try:
            resp = requests.get(
                f"{self.base_url}/users/me",
                auth=HTTPBasicAuth(self.username, self.password),
                params={"context": "edit"},
                timeout=10,
            )
            return resp.ok
        except Exception:
            return False


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
