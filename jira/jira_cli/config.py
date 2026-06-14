"""Configuration management for Jira CLI."""

from pathlib import Path
from typing import Optional

from dotenv import dotenv_values

from cli_tools_shared.config import BaseConfig, get_profiles_base_dir, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ClientError

SITE_BASIC_AUTH_TYPE = "site_basic"
OAUTH_3LO_AUTH_TYPE = "oauth_authorization_code"
SCOPED_API_TOKEN_AUTH_TYPE = "scoped_api_token"

SCOPED_TOKEN_PROFILE_PROMPTS = (
    ("CLOUD_ID", "Jira Cloud ID", False),
)

OAUTH_PROFILE_PROMPTS = (
    ("BASE_URL", "Jira Cloud site URL (for example https://example.atlassian.net)", False),
)

OAUTH_LOGIN_PROMPTS = (
    ("CLIENT_ID", "Client ID", False),
    ("CLIENT_SECRET", "Client Secret", True),
    ("REDIRECT_URI", "Redirect URI", False),
)

SITE_BASIC_LOGIN_PROMPTS = (
    ("USERNAME", "Atlassian account email", False),
    ("PASSWORD", "Atlassian API token", True),
)

SCOPED_TOKEN_LOGIN_PROMPTS = (
    ("CLOUD_ID", "Jira Cloud ID", False),
    ("USERNAME", "Atlassian account email", False),
    ("PASSWORD", "Scoped Atlassian API token", True),
)


def _migrate_legacy_profiles(tool_name: str) -> None:
    profiles_dir = get_profiles_base_dir(tool_name)
    if not profiles_dir.exists():
        return
    for env_path in profiles_dir.glob("*/.env"):
        values = dotenv_values(env_path)
        if values.get("AUTH_TYPE"):
            continue
        if values.get("USERNAME") or values.get("PASSWORD"):
            env_path.write_text(f"AUTH_TYPE={SITE_BASIC_AUTH_TYPE}\n{env_path.read_text()}")


def migrate_legacy_profiles() -> None:
    tool_dir = resolve_tool_dir(Config.DIST_NAME)
    _migrate_legacy_profiles(tool_dir.name)


class Config(BaseConfig):
    DIST_NAME = "jira-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_ALL_FIELDS = [
        "AUTH_TYPE",
        "USERNAME",
        "PASSWORD",
        "CLIENT_ID",
        "CLIENT_SECRET",
        "ACCESS_TOKEN",
        "REFRESH_TOKEN",
        "TOKEN_EXPIRES_AT",
        "REDIRECT_URI",
        "CLOUD_ID",
    ]
    PROFILE_AUTH_TYPE_FIELD = "AUTH_TYPE"
    PROFILE_AUTH_TYPES = {
        SITE_BASIC_AUTH_TYPE: [],
        OAUTH_3LO_AUTH_TYPE: list(OAUTH_PROFILE_PROMPTS),
        SCOPED_API_TOKEN_AUTH_TYPE: list(SCOPED_TOKEN_PROFILE_PROMPTS),
    }
    DEFAULT_BASE_URL = "https://your-domain.atlassian.net"
    AUTH_CONFIG_PROMPTS = [
        ("BASE_URL", "Jira Cloud site URL (for example https://example.atlassian.net)", False),
    ]

    def __init__(self, profile=None):
        tool_dir = resolve_tool_dir(self.DIST_NAME)
        _migrate_legacy_profiles(tool_dir.name)
        super().__init__(
            tool_dir=tool_dir,
            profile=profile,
        )

    @property
    def storage_dir(self) -> Path:
        """Profile-aware storage directory for runtime state."""
        return self.get_profile_data_dir()

    @property
    def auth_type(self) -> Optional[str]:
        return self._get(self.PROFILE_AUTH_TYPE_FIELD)

    @property
    def cloud_id(self) -> Optional[str]:
        return self._get("CLOUD_ID")

    @property
    def CUSTOM_REQUIRED_FIELDS(self) -> list[str]:
        auth_type = self.auth_type
        if auth_type == SITE_BASIC_AUTH_TYPE:
            return ["AUTH_TYPE", "USERNAME", "PASSWORD"]
        if auth_type == SCOPED_API_TOKEN_AUTH_TYPE:
            return ["AUTH_TYPE", "CLOUD_ID", "USERNAME", "PASSWORD"]
        if auth_type == OAUTH_3LO_AUTH_TYPE:
            return ["AUTH_TYPE", "CLIENT_ID", "CLIENT_SECRET", "REDIRECT_URI", "ACCESS_TOKEN", "CLOUD_ID"]
        return ["AUTH_TYPE"]

    @property
    def CUSTOM_LOGIN_PROMPTS(self) -> list[tuple[str, str, bool]]:
        auth_type = self.auth_type
        if auth_type == SITE_BASIC_AUTH_TYPE:
            return list(SITE_BASIC_LOGIN_PROMPTS)
        if auth_type == SCOPED_API_TOKEN_AUTH_TYPE:
            return list(SCOPED_TOKEN_LOGIN_PROMPTS)
        if auth_type == OAUTH_3LO_AUTH_TYPE:
            return list(OAUTH_LOGIN_PROMPTS)
        return []

    @property
    def CUSTOM_EPHEMERAL_FIELDS(self) -> list[str]:
        auth_type = self.auth_type
        if auth_type == SITE_BASIC_AUTH_TYPE:
            return ["USERNAME", "PASSWORD"]
        if auth_type == SCOPED_API_TOKEN_AUTH_TYPE:
            return ["USERNAME", "PASSWORD"]
        if auth_type == OAUTH_3LO_AUTH_TYPE:
            return ["CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN", "TOKEN_EXPIRES_AT", "REDIRECT_URI"]
        return []

    @property
    def CUSTOM_SENSITIVE_FIELDS(self) -> list[str]:
        auth_type = self.auth_type
        if auth_type in {SITE_BASIC_AUTH_TYPE, SCOPED_API_TOKEN_AUTH_TYPE}:
            return ["USERNAME", "PASSWORD"]
        if auth_type == OAUTH_3LO_AUTH_TYPE:
            return ["CLIENT_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN"]
        return []

    @property
    def AUTH_SETUP_INSTRUCTIONS(self) -> str:
        auth_type = self.auth_type
        if auth_type == SITE_BASIC_AUTH_TYPE:
            return (
                "Before logging in:\n"
                "  1. Create an Atlassian API token at\n"
                "     https://id.atlassian.com/manage-profile/security/api-tokens.\n"
                "  2. Enter the Atlassian account email as USERNAME and the classic token as PASSWORD.\n"
                "  3. Classic site basic auth calls https://<site>.atlassian.net/rest/api/3/..."
            )
        if auth_type == SCOPED_API_TOKEN_AUTH_TYPE:
            return (
                "Before logging in:\n"
                "  1. Create an Atlassian API token with Jira scopes at\n"
                "     https://id.atlassian.com/manage-profile/security/api-tokens.\n"
                "  2. Enter the Jira Cloud ID for the target site.\n"
                "  3. Enter the Atlassian account email as USERNAME and the scoped token as PASSWORD.\n"
                "  4. Scoped tokens call https://api.atlassian.com/ex/jira/{cloudId}/..."
            )
        if auth_type == OAUTH_3LO_AUTH_TYPE:
            return (
                "Before logging in:\n"
                "  1. Create an OAuth 2.0 (3LO) app in the Atlassian Developer Console.\n"
                "  2. Add classic Jira scopes read:jira-user, read:jira-work, write:jira-work,\n"
                "     plus offline_access if you want refresh tokens.\n"
                "  3. Add a callback URL such as http://localhost.\n"
                "  4. Enter the Client ID, Client Secret, and Redirect URI below."
            )
        return ""

    @property
    def OAUTH_AUTH_URL(self) -> str:
        if self.auth_type != OAUTH_3LO_AUTH_TYPE:
            return ""
        return "https://auth.atlassian.com/authorize"

    @property
    def OAUTH_TOKEN_URL(self) -> str:
        if self.auth_type != OAUTH_3LO_AUTH_TYPE:
            return ""
        return "https://auth.atlassian.com/oauth/token"

    OAUTH_SCOPES = [
        "offline_access",
        "read:jira-user",
        "read:jira-work",
        "write:jira-work",
    ]
    OAUTH_REDIRECT_URI = "http://localhost"
    OAUTH_TOKEN_AUTH = "body"

    def has_credentials(self) -> bool:
        auth_type = self.auth_type
        if auth_type == SITE_BASIC_AUTH_TYPE:
            return bool(self.username and self.password)
        if auth_type == SCOPED_API_TOKEN_AUTH_TYPE:
            return bool(self.username and self.password and self.cloud_id)
        if auth_type == OAUTH_3LO_AUTH_TYPE:
            return bool(self.client_id and self.client_secret and self.access_token and self.cloud_id)
        return False

    def get_missing_credentials(self) -> list[str]:
        auth_type = self.auth_type
        if auth_type == SITE_BASIC_AUTH_TYPE:
            required = ["USERNAME", "PASSWORD"]
        elif auth_type == SCOPED_API_TOKEN_AUTH_TYPE:
            required = ["USERNAME", "PASSWORD", "CLOUD_ID"]
        elif auth_type == OAUTH_3LO_AUTH_TYPE:
            required = ["CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN", "CLOUD_ID"]
        else:
            required = [self.PROFILE_AUTH_TYPE_FIELD]
        return [field for field in required if not self._get(field)]

    def test_connection(self) -> dict:
        """Validate saved credentials with a live API call."""
        from .client import JiraClient

        try:
            user = JiraClient(config=self).get_myself()
            return {
                "api_test": "passed",
                "account_id": user.get("accountId", ""),
                "display_name": user.get("displayName", ""),
                "email": user.get("emailAddress", ""),
            }
        except ClientError as exc:
            return {"api_test": f"failed: {exc}"}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
