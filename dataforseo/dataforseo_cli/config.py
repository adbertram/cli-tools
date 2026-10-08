"""Configuration management for Dataforseo CLI."""

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ClientError


class Config(BaseConfig):
    DIST_NAME = "dataforseo-cli"
    CREDENTIAL_TYPES = [CredentialType.USERNAME_PASSWORD]
    DEFAULT_BASE_URL = "https://api.dataforseo.com"
    AUTH_SETUP_INSTRUCTIONS = (
        "Use the API login and API password from the API Access page of the DataForSEO "
        "dashboard, not the website password."
    )

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def test_connection(self) -> dict:
        """Validate saved credentials with a live API call."""
        from .client import DataforseoClient

        try:
            DataforseoClient(config=self).get_user_data()
            return {"api_test": "passed"}
        except ClientError as exc:
            return {"api_test": f"failed: {exc}"}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
