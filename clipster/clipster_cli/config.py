"""Configuration management for Clipster CLI."""

from cli_tools_shared.config import BaseConfig, config_for, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ClientError, CredentialError

TOKEN_FIELDS = ["ACCESS_TOKEN", "REFRESH_TOKEN", "TOKEN_EXPIRES_AT", "REFRESH_EXPIRES_AT"]


class Config(BaseConfig):
    DIST_NAME = "clipster-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DEFAULT_BASE_URL = "https://api.clipster.gg"
    # EMAIL is the login identifier, so it lives in the CLI-tools secret manager.
    # Tokens are runtime state written by `auth login` and automatic refresh.
    CUSTOM_REQUIRED_FIELDS = ["EMAIL", "REFRESH_TOKEN"]
    CUSTOM_ALL_FIELDS = ["EMAIL", *TOKEN_FIELDS]
    CUSTOM_LOGIN_PROMPTS = [("EMAIL", "Clipster account email", False)]
    CUSTOM_EPHEMERAL_FIELDS = TOKEN_FIELDS
    CUSTOM_SENSITIVE_FIELDS = ["EMAIL"]
    AUTH_SETUP_INSTRUCTIONS = (
        "Clipster signs in with an emailed one-time passcode. `auth login` requests the\n"
        "passcode, reads it from Gmail with the `google` CLI, and saves the session."
    )

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def test_connection(self) -> dict:
        """Live identity check; refreshes an expired session but never sends a passcode."""
        from .client import ClipsterClient

        try:
            user = ClipsterClient(config=self).account(allow_login=False)
            return {"api_test": "passed", "email": user["email"], "user_id": user["id"]}
        except (ClientError, CredentialError) as exc:
            return {"api_test": f"failed: {exc}"}


_configs = {}


def get_config(profile=None):
    return config_for(Config, profile, _configs)
