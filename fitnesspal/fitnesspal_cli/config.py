"""Configuration management for Fitnesspal CLI."""
from pathlib import Path
from typing import Optional
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):

    DIST_NAME = "fitnesspal-cli"
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://www.myfitnesspal.com"
    ADDITIONAL_AUTH_FIELDS = ("USERNAME", "PASSWORD")
    ADDITIONAL_SENSITIVE_AUTH_FIELDS = ("USERNAME", "PASSWORD")

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def get_browser(self):
        """Return MyFitnessPalBrowser instance for browser-based login."""
        from .browser import MyFitnessPalBrowser
        return MyFitnessPalBrowser(self)

    def test_connection(self) -> Optional[dict]:
        """Test connectivity using saved browser session cookies."""
        try:
            from .client import _load_cookiejar
            import myfitnesspal
            cookiejar = _load_cookiejar()
            client = myfitnesspal.Client(cookiejar=cookiejar)
            username = client.effective_username
            return {"api_test": "passed", "username": username}
        except Exception as e:
            return {"api_test": f"failed: {e}"}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
