"""Configuration management for Facebook CLI."""
from pathlib import Path

import requests
from dotenv import dotenv_values, set_key, unset_key

from cli_tools_shared.browser.user_agent import derive_real_chrome_user_agent
from cli_tools_shared.config import (
    BaseConfig,
    _secret_name_for_profile_field,
    _secret_name_from_placeholder,
    _secret_exists,
    _set_secret_value,
    get_profiles_base_dir,
    profile_name_from_path,
    read_cli_tool_secret,
    resolve_tool_dir,
)
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ConfigError

API_AUTH_TYPE = CredentialType.OAUTH_AUTHORIZATION_CODE.value
BROWSER_AUTH_TYPE = CredentialType.BROWSER_SESSION.value
DEFAULT_GRAPH_VERSION = "v24.0"
FACEBOOK_OAUTH_SCOPES = [
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
]
BROWSER_LOGIN_FIELDS = ("USERNAME", "PASSWORD")


def browser_login_secret_name(profile_name: str, field_name: str) -> str:
    """Return the canonical browser-login secret name for a profile field."""
    return _secret_name_for_profile_field("facebook", field_name, profile_name)


def _sanitize_legacy_profile(env_path: Path, values: dict[str, str | None]) -> None:
    """Mark a legacy profile as browser auth and remove migrated credentials."""
    if not values.get("AUTH_TYPE"):
        set_key(env_path, "AUTH_TYPE", BROWSER_AUTH_TYPE, quote_mode="never")
    for field_name in BROWSER_LOGIN_FIELDS:
        if field_name in values:
            removed, _ = unset_key(env_path, field_name, quote_mode="never")
            if not removed:
                raise ConfigError(
                    f"Failed to remove migrated {field_name} from {env_path}."
                )


def _migrate_legacy_browser_login_field(
    env_path: Path,
    profile_name: str,
    field_name: str,
    value: str | None,
) -> None:
    """Move one legacy reusable browser credential into the secret manager."""
    if not value:
        return

    target_secret = browser_login_secret_name(profile_name, field_name)
    source_secret = _secret_name_from_placeholder(value)
    if source_secret is not None:
        if source_secret == target_secret:
            if not _secret_exists(target_secret):
                raise ConfigError(
                    f"Missing CLI-tools secret '{target_secret}' referenced by {env_path}."
                )
            return
        if _secret_exists(target_secret):
            return
        source_value = read_cli_tool_secret(source_secret)
        if source_value is None:
            raise ConfigError(
                f"Missing CLI-tools secret '{source_secret}' referenced by {env_path}."
            )
        _set_secret_value(target_secret, source_value, env_path)
        return

    # Once a canonical secret exists it is the source of truth. Do not replace
    # it with a stale profile value during migration.
    if not _secret_exists(target_secret):
        _set_secret_value(target_secret, value, env_path)


def migrate_legacy_profiles() -> None:
    """Migrate legacy browser credentials before BaseConfig validates profiles."""
    profiles_dir = get_profiles_base_dir(resolve_tool_dir(Config.DIST_NAME).name)
    if not profiles_dir.exists():
        return
    for env_path in sorted(profiles_dir.glob("*/.env")):
        values = dotenv_values(env_path)
        profile_name = profile_name_from_path(env_path)
        for field_name in BROWSER_LOGIN_FIELDS:
            _migrate_legacy_browser_login_field(
                env_path,
                profile_name,
                field_name,
                values.get(field_name),
            )
        if not values.get("AUTH_TYPE") or any(
            field_name in values for field_name in BROWSER_LOGIN_FIELDS
        ):
            _sanitize_legacy_profile(env_path, values)


class Config(BaseConfig):
    """Configuration manager for Facebook browser and Graph API access."""

    DIST_NAME = "facebook-cli"

    CREDENTIAL_TYPES = [
        CredentialType.OAUTH_AUTHORIZATION_CODE,
        CredentialType.BROWSER_SESSION,
    ]
    PROFILE_AUTH_TYPE_FIELD = "AUTH_TYPE"
    PROFILE_AUTH_TYPES = {
        API_AUTH_TYPE: [],
        BROWSER_AUTH_TYPE: [],
    }

    DEFAULT_BASE_URL = "https://www.facebook.com"
    OAUTH_AUTH_URL = f"https://www.facebook.com/{DEFAULT_GRAPH_VERSION}/dialog/oauth"
    OAUTH_TOKEN_URL = f"https://graph.facebook.com/{DEFAULT_GRAPH_VERSION}/oauth/access_token"
    OAUTH_SCOPES = FACEBOOK_OAUTH_SCOPES
    OAUTH_TOKEN_AUTH = "body"
    OAUTH_TOKEN_EXPIRES = False

    LOGIN_INSTRUCTIONS = (
        "Facebook has separate browser and Graph API profiles.\n"
        "  - Existing Marketplace/Groups/Messenger workflows use browser_session.\n"
        "  - Pages/Reels publishing uses oauth_authorization_code. Create a Meta app,\n"
        "    configure a Facebook Login redirect URI, and request pages_show_list,\n"
        "    pages_read_engagement, and pages_manage_posts.\n"
        "Create/select the matching auth profile, then run facebook auth login\n"
        "with --credential-type for that profile."
    )

    def __init__(self, profile=None, profile_auth_type=None):
        migrate_legacy_profiles()
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
            profile_auth_type=profile_auth_type,
        )

    def _resolve_env_file(self, profile=None, profile_auth_type=None):
        """Repair the default profile BaseConfig creates during this initialization."""
        migrate_legacy_profiles()
        return super()._resolve_env_file(
            profile=profile,
            profile_auth_type=profile_auth_type,
        )

    @property
    def auth_type(self):
        return self._get(self.PROFILE_AUTH_TYPE_FIELD)

    @property
    def graph_version(self) -> str:
        return self._get("GRAPH_VERSION") or DEFAULT_GRAPH_VERSION

    @property
    def graph_base_url(self) -> str:
        return f"https://graph.facebook.com/{self.graph_version}"

    @property
    def browser_user_agent(self) -> str:
        """Use the installed real-Chrome UA for headed and headless sessions."""
        override = self._get("BROWSER_USER_AGENT")
        if override:
            return override
        return derive_real_chrome_user_agent()

    @property
    def cache_dir(self) -> Path:
        """Get the per-profile cache directory."""
        d = self.storage_dir / "cache"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get_browser(self):
        """Return browser service for Facebook browser-based auth."""
        from .browser import FacebookBrowser
        return FacebookBrowser(self)

    def has_credentials(self) -> bool:
        """Check credentials for the active Facebook auth profile type."""
        if self.auth_type == API_AUTH_TYPE:
            return bool(self.client_id and self.client_secret and self.access_token)
        return self.has_saved_session()

    def get_missing_credentials(self) -> list[str]:
        if self.auth_type == API_AUTH_TYPE:
            required = ("CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN")
            return [field for field in required if not self._get(field)]
        return [] if self.has_saved_session() else ["browser_session"]

    def test_connection(self):
        """Test the active API or browser profile."""
        if self.auth_type == API_AUTH_TYPE:
            if not self.access_token:
                return {"api_test": "failed: missing ACCESS_TOKEN"}
            try:
                response = requests.get(
                    f"{self.graph_base_url}/me",
                    params={"fields": "id,name"},
                    headers={"Authorization": f"Bearer {self.access_token}"},
                    timeout=30,
                )
                if not response.ok:
                    return {
                        "api_test": f"failed: HTTP {response.status_code}: {response.text[:500]}"
                    }
                payload = response.json()
                return {
                    "api_test": "passed",
                    "user_id": payload.get("id"),
                    "name": payload.get("name"),
                }
            except Exception as exc:
                return {"api_test": f"failed: {exc}"}

        browser = self.get_browser()
        if not self.has_saved_session():
            return {"api_test": "failed: no active browser session"}
        try:
            result = browser.test_session()
            if result.get("authenticated"):
                return {"api_test": "passed (browser session active)"}
            return {"api_test": f"failed: {result.get('error', 'not authenticated')}"}
        except Exception as exc:
            return {"api_test": f"failed: {exc}"}


_configs = {}


def get_config(profile=None, profile_auth_type=None):
    """Get or create a config instance for the given profile."""
    key = (profile or "_default", profile_auth_type or "_any")
    if key not in _configs:
        _configs[key] = Config(profile=profile, profile_auth_type=profile_auth_type)
    return _configs[key]
