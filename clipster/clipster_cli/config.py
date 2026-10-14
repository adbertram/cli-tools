"""Configuration management for Clipster CLI."""

from cli_tools_shared.config import BaseConfig, config_for, resolve_tool_dir
from cli_tools_shared.exceptions import ClientError


class Config(BaseConfig):
    DIST_NAME = "clipster-cli"
    CREDENTIAL_TYPES = []
    DEFAULT_BASE_URL = "https://api.clipster.gg"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def test_connection(self) -> dict:
        """Validate the public API connection with a live API call."""
        from .client import ClipsterClient

        try:
            ClipsterClient(config=self).list_campaigns(limit=1)
            return {"api_test": "passed"}
        except ClientError as exc:
            return {"api_test": f"failed: {exc}"}


_configs = {}


def get_config(profile=None):
    return config_for(Config, profile, _configs)
