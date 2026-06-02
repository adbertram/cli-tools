"""Configuration management for DoorDash CLI."""
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.http_session import BrowserAuthState


class Config(BaseConfig):
    DIST_NAME = "doordash-cli"
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://www.doordash.com"

    def __init__(self, profile=None):
        super().__init__(tool_dir=resolve_tool_dir(self.DIST_NAME), profile=profile)

    @property
    def default_latitude(self) -> Optional[float]:
        value = self._get("LATITUDE")
        return float(value) if value else None

    @property
    def default_longitude(self) -> Optional[float]:
        value = self._get("LONGITUDE")
        return float(value) if value else None

    def get_browser(self):
        from .browser import DoorDashBrowser

        return DoorDashBrowser(self)

    def test_connection(self) -> dict:
        BrowserAuthState.from_config(self).cookies_for_host(
            "www.doordash.com",
            allowed_domains=("doordash.com",),
        )
        return {"api_test": "passed"}

    @property
    def storage_dir(self) -> Path:
        return self.get_profile_data_dir()


_configs = {}


def get_config(profile=None) -> Config:
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
