"""Configuration management for Mailchimp CLI."""
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Mailchimp CLI configuration (API key auth)."""

    DIST_NAME = "mailchimp-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DEFAULT_BASE_URL = "https://usX.api.mailchimp.com/3.0"
    CUSTOM_REQUIRED_FIELDS = ["MAILCHIMP_API_KEY"]
    CUSTOM_ALL_FIELDS = [
        "MAILCHIMP_API_KEY",
        "MAILCHIMP_CLIENT_ID",
        "MAILCHIMP_CLIENT_SECRET",
        "MAILCHIMP_ACCESS_TOKEN",
        "MAILCHIMP_REFRESH_TOKEN",
        "MAILCHIMP_TOKEN_EXPIRES_AT",
        "MAILCHIMP_BASE_URL",
    ]
    CUSTOM_LOGIN_PROMPTS = [("MAILCHIMP_API_KEY", "Mailchimp API key", True)]
    CUSTOM_EPHEMERAL_FIELDS = [
        "MAILCHIMP_ACCESS_TOKEN",
        "MAILCHIMP_REFRESH_TOKEN",
        "MAILCHIMP_TOKEN_EXPIRES_AT",
    ]
    CUSTOM_SENSITIVE_FIELDS = [
        "MAILCHIMP_API_KEY",
        "MAILCHIMP_CLIENT_SECRET",
        "MAILCHIMP_ACCESS_TOKEN",
        "MAILCHIMP_REFRESH_TOKEN",
    ]

    LOGIN_INSTRUCTIONS = (
        "To get your Mailchimp API key:\n"
        "  1. Go to Mailchimp Account & billing > Extras > API keys\n"
        "  2. Create or copy an API key\n"
        "  3. Paste the key below"
    )

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def api_key(self) -> Optional[str]:
        return self._get("MAILCHIMP_API_KEY")

    @property
    def client_id(self) -> Optional[str]:
        return self._get("MAILCHIMP_CLIENT_ID")

    @property
    def client_secret(self) -> Optional[str]:
        return self._get("MAILCHIMP_CLIENT_SECRET")

    @property
    def access_token(self) -> Optional[str]:
        return self._get("MAILCHIMP_ACCESS_TOKEN")

    @property
    def refresh_token(self) -> Optional[str]:
        return self._get("MAILCHIMP_REFRESH_TOKEN")

    @property
    def token_expires_at(self) -> Optional[str]:
        return self._get("MAILCHIMP_TOKEN_EXPIRES_AT")

    @property
    def base_url(self) -> str:
        return self._get("MAILCHIMP_BASE_URL") or self.DEFAULT_BASE_URL

    def has_credentials(self) -> bool:
        """Mailchimp accepts either an API key or a stored OAuth access token."""
        return bool(self.api_key or self.access_token)

    def get_missing_credentials(self) -> list[str]:
        if self.has_credentials():
            return []
        return ["MAILCHIMP_API_KEY or MAILCHIMP_ACCESS_TOKEN"]

    def test_connection(self) -> Optional[dict]:
        """Verify credentials by fetching account metadata."""
        from .client import MailchimpClient, ClientError
        try:
            account = MailchimpClient(config=self).get_account()
            return {
                "api_test": "passed",
                "account_id": account.get("account_id", ""),
                "account_name": account.get("account_name", ""),
            }
        except ClientError as e:
            return {"api_test": f"failed: {e}"}


_configs: dict = {}


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create a config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
