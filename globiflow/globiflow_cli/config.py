"""Configuration management for Globiflow CLI."""

from pathlib import Path
from typing import Optional

from cli_tools_shared.http_session import BrowserAuthState
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Globiflow configuration backed by cli_tools_shared profiles."""

    DIST_NAME = "globiflow-cli"
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://workflow-automation.podio.com"
    ADDITIONAL_AUTH_FIELDS = ("USERNAME", "PASSWORD")
    ADDITIONAL_SENSITIVE_AUTH_FIELDS = ("USERNAME", "PASSWORD")

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def headless(self) -> bool:
        return (self._get("HEADLESS") or "true").lower() == "true"

    def get_browser(self):
        from .browser import GlobiflowBrowser

        return GlobiflowBrowser(self)

    def test_connection(self) -> dict:
        BrowserAuthState.from_config(self)
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
