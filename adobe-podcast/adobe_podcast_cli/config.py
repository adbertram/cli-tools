"""Configuration management for AdobePodcast CLI."""

from pathlib import Path

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    DIST_NAME = "adobe-podcast-cli"
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://phonos-server-flex.adobe.io"
    # Uncomment when auth login needs required non-secret config first.
    # AUTH_CONFIG_PROMPTS = [("BASE_URL", "AdobePodcast base URL", False)]
    # Uncomment when the user must create a token/app before logging in.
    # AUTH_SETUP_INSTRUCTIONS = (
    #     "Before logging in:\n"
    #     "  1. Create the required token/app: https://example.com/settings/api\n"
    #     "  2. Follow the service instructions, then continue here."
    # )

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def storage_dir(self) -> Path:
        """Profile-aware storage directory for runtime state."""
        return self.get_profile_data_dir()

    def get_browser(self):
        """Return the browser automation instance for this config."""
        from .browser import AdobePodcastBrowser
        return AdobePodcastBrowser(self)

    def test_connection(self) -> dict:
        """Validate saved credentials by checking the access token is present."""
        if not self.access_token:
            return {"api_test": "failed: no access token — run 'adobe-podcast auth login'"}
        return {"api_test": "passed"}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
