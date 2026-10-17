"""Configuration management for Envato CLI."""

from cli_tools_shared.config import BaseConfig, config_for, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ClientError


class Config(BaseConfig):
    DIST_NAME = "envato-cli"
    CREDENTIAL_TYPES = [CredentialType.PERSONAL_ACCESS_TOKEN]
    DEFAULT_BASE_URL = "https://api.envato.com"
    # The personal token lives in the CLI-tools secret manager under this name.
    SECRET_NAME_OVERRIDES = {"PERSONAL_ACCESS_TOKEN": "envato-api-token"}
    AUTH_SETUP_INSTRUCTIONS = (
        "Before logging in:\n"
        "  1. Create a personal token at https://build.envato.com/create-token/\n"
        "  2. Grant 'View and search Envato sites' and 'View the user's Envato Account username'.\n"
        "  3. Paste the token below; it is stored in the CLI-tools secret manager as 'envato-api-token'."
    )

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def test_connection(self) -> dict:
        """Validate the saved token with a live username lookup."""
        from .client import EnvatoClient

        try:
            username = EnvatoClient(config=self).get_username()
            return {"api_test": "passed", "username": username}
        except ClientError as exc:
            return {"api_test": f"failed: {exc}"}


_configs = {}


def get_config(profile=None):
    return config_for(Config, profile, _configs)
