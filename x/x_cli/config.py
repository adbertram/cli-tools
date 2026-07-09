"""Configuration management for X CLI."""

from typing import Optional

from dotenv import dotenv_values

from cli_tools_shared.config import BaseConfig, get_profiles_base_dir, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType

API_AUTH_TYPE = CredentialType.CUSTOM.value
BROWSER_AUTH_TYPE = CredentialType.BROWSER_SESSION.value

X_API_REQUIRED_FIELDS = [
    "X_CONSUMER_KEY",
    "X_CONSUMER_SECRET",
    "X_ACCESS_TOKEN",
    "X_ACCESS_TOKEN_SECRET",
]

X_API_ALL_FIELDS = [
    "AUTH_TYPE",
    *X_API_REQUIRED_FIELDS,
    "X_BEARER_TOKEN",
    "X_BASE_URL",
]

X_API_LOGIN_PROMPTS = [
    ("X_CONSUMER_KEY", "Consumer Key (API Key)", False),
    ("X_CONSUMER_SECRET", "Consumer Secret (API Secret)", True),
    ("X_ACCESS_TOKEN", "Access Token", False),
    ("X_ACCESS_TOKEN_SECRET", "Access Token Secret", True),
]

X_API_SENSITIVE_FIELDS = [
    "X_CONSUMER_KEY",
    "X_CONSUMER_SECRET",
    "X_ACCESS_TOKEN",
    "X_ACCESS_TOKEN_SECRET",
    "X_BEARER_TOKEN",
]


def _migrate_legacy_profiles(tool_name: str) -> None:
    profiles_dir = get_profiles_base_dir(tool_name)
    if not profiles_dir.exists():
        return
    for env_path in profiles_dir.glob("*/.env"):
        values = dotenv_values(env_path)
        if values.get("AUTH_TYPE"):
            continue
        env_path.write_text(f"AUTH_TYPE={API_AUTH_TYPE}\n{env_path.read_text()}")


class Config(BaseConfig):
    """X CLI configuration."""

    DIST_NAME = "x-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM, CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://api.twitter.com"
    PROFILE_AUTH_TYPE_FIELD = "AUTH_TYPE"
    PROFILE_AUTH_TYPES = {
        API_AUTH_TYPE: [],
        BROWSER_AUTH_TYPE: [],
    }
    CUSTOM_REQUIRED_FIELDS = [
        "AUTH_TYPE",
        "X_CONSUMER_KEY",
        "X_CONSUMER_SECRET",
        "X_ACCESS_TOKEN",
        "X_ACCESS_TOKEN_SECRET",
    ]
    CUSTOM_ALL_FIELDS = [
        "AUTH_TYPE",
        "X_CONSUMER_KEY",
        "X_CONSUMER_SECRET",
        "X_ACCESS_TOKEN",
        "X_ACCESS_TOKEN_SECRET",
        "X_BEARER_TOKEN",
        "X_BASE_URL",
    ]
    CUSTOM_LOGIN_PROMPTS = [
        ("X_CONSUMER_KEY", "Consumer Key (API Key)", False),
        ("X_CONSUMER_SECRET", "Consumer Secret (API Secret)", True),
        ("X_ACCESS_TOKEN", "Access Token", False),
        ("X_ACCESS_TOKEN_SECRET", "Access Token Secret", True),
    ]
    CUSTOM_SENSITIVE_FIELDS = [
        "X_CONSUMER_KEY",
        "X_CONSUMER_SECRET",
        "X_ACCESS_TOKEN",
        "X_ACCESS_TOKEN_SECRET",
        "X_BEARER_TOKEN",
    ]
    CUSTOM_EPHEMERAL_FIELDS = []

    LOGIN_INSTRUCTIONS = (
        "To get your X API OAuth 1.0a credentials:\n"
        "  1. Go to https://developer.x.com/en/portal/dashboard\n"
        "  2. Create or open an app\n"
        "  3. Under 'Keys and tokens' generate:\n"
        "     - Consumer Key / Consumer Secret (API Key / Secret)\n"
        "     - Access Token / Access Token Secret (User authentication tokens)"
    )

    def __init__(self, profile=None, profile_auth_type=None):
        tool_dir = resolve_tool_dir(self.DIST_NAME)
        _migrate_legacy_profiles(tool_dir.name)
        super().__init__(
            tool_dir=tool_dir,
            profile=profile,
            profile_auth_type=profile_auth_type,
        )

    @property
    def auth_type(self) -> Optional[str]:
        return self._get(self.PROFILE_AUTH_TYPE_FIELD)

    @property
    def CUSTOM_REQUIRED_FIELDS(self) -> list[str]:
        if self.auth_type == BROWSER_AUTH_TYPE:
            return ["AUTH_TYPE"]
        return ["AUTH_TYPE", *X_API_REQUIRED_FIELDS]

    @property
    def CUSTOM_LOGIN_PROMPTS(self) -> list[tuple[str, str, bool]]:
        if self.auth_type == BROWSER_AUTH_TYPE:
            return []
        return list(X_API_LOGIN_PROMPTS)

    @property
    def CUSTOM_SENSITIVE_FIELDS(self) -> list[str]:
        if self.auth_type == BROWSER_AUTH_TYPE:
            return []
        return list(X_API_SENSITIVE_FIELDS)

    @property
    def consumer_key(self) -> Optional[str]:
        return self._get("X_CONSUMER_KEY")

    @property
    def consumer_secret(self) -> Optional[str]:
        return self._get("X_CONSUMER_SECRET")

    @property
    def access_token(self) -> Optional[str]:
        return self._get("X_ACCESS_TOKEN")

    @property
    def access_token_secret(self) -> Optional[str]:
        return self._get("X_ACCESS_TOKEN_SECRET")

    @property
    def bearer_token(self) -> Optional[str]:
        return self._get("X_BEARER_TOKEN")

    @property
    def base_url(self) -> str:
        return self._get("X_BASE_URL") or self.DEFAULT_BASE_URL

    @property
    def headless(self) -> bool:
        """Run saved browser-session commands headlessly by default."""
        return True

    @property
    def credit_card_lastpass_item_id(self) -> Optional[str]:
        return self._get("X_CREDIT_CARD_LASTPASS_ITEM_ID")

    @property
    def billing_address_line1(self) -> Optional[str]:
        return self._get("X_BILLING_ADDRESS_LINE1")

    @property
    def billing_address_line2(self) -> Optional[str]:
        return self._get("X_BILLING_ADDRESS_LINE2")

    @property
    def billing_city(self) -> Optional[str]:
        return self._get("X_BILLING_CITY")

    @property
    def billing_state(self) -> Optional[str]:
        return self._get("X_BILLING_STATE")

    @property
    def billing_postal_code(self) -> Optional[str]:
        return self._get("X_BILLING_POSTAL_CODE")

    @property
    def billing_country(self) -> str:
        return self._get("X_BILLING_COUNTRY") or "US"

    @property
    def billing_phone(self) -> Optional[str]:
        return self._get("X_BILLING_PHONE")

    def has_bearer_token(self) -> bool:
        """Check if bearer token is available for read-only operations."""
        return bool(self.bearer_token)

    def has_api_credentials(self) -> bool:
        """Check whether OAuth 1.0a API credentials are complete."""
        return all(self._get(field) for field in X_API_REQUIRED_FIELDS)

    def get_missing_api_credentials(self) -> list[str]:
        """Return missing OAuth 1.0a API credential fields."""
        return [field for field in X_API_REQUIRED_FIELDS if not self._get(field)]

    def has_credentials(self) -> bool:
        """Check credentials for the active X auth profile type."""
        if self.auth_type == BROWSER_AUTH_TYPE:
            return self.has_saved_session()
        return self.has_api_credentials()

    def get_missing_credentials(self) -> list[str]:
        """Return missing credentials for the active X auth profile type."""
        if self.auth_type == BROWSER_AUTH_TYPE:
            return [] if self.has_saved_session() else ["browser_session"]
        return self.get_missing_api_credentials()

    def get_browser(self):
        """Return browser automation for X Developer Console actions."""
        from .browser import XBrowser

        return XBrowser(self)

    def test_connection(self) -> Optional[dict]:
        """Verify the active X auth profile."""
        if self.auth_type == BROWSER_AUTH_TYPE:
            return self.get_browser().test_session()

        from .client import ClientError, XClient

        try:
            client = XClient(config=self)
            user = client.get_me()
            return {
                "api_test": "passed",
                "user_id": user.get("id", ""),
                "username": user.get("username", ""),
                "name": user.get("name", ""),
            }
        except ClientError as e:
            return {"api_test": f"failed: {e}"}


_configs: dict = {}


def get_config(profile=None, profile_auth_type=None) -> Config:
    """Get or create a config instance for the given profile."""
    key = (profile or "_default", profile_auth_type or "_any")
    if key not in _configs:
        _configs[key] = Config(profile=profile, profile_auth_type=profile_auth_type)
    return _configs[key]
