"""Configuration management for Facebook CLI."""
from pathlib import Path

import requests
from dotenv import dotenv_values

from cli_tools_shared.browser.user_agent import derive_real_chrome_user_agent
from cli_tools_shared.config import BaseConfig, get_profiles_base_dir, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType

API_AUTH_TYPE = CredentialType.OAUTH_AUTHORIZATION_CODE.value
BROWSER_AUTH_TYPE = CredentialType.BROWSER_SESSION.value
DEFAULT_GRAPH_VERSION = "v24.0"
FACEBOOK_OAUTH_SCOPES = [
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
]


def _migrate_legacy_profiles(tool_name: str) -> None:
    """Mark pre-Graph-API profiles as browser-session profiles."""
    profiles_dir = get_profiles_base_dir(tool_name)
    if not profiles_dir.exists():
        return
    for env_path in profiles_dir.glob("*/.env"):
        values = dotenv_values(env_path)
        if values.get("AUTH_TYPE"):
            continue
        env_path.write_text(f"AUTH_TYPE={BROWSER_AUTH_TYPE}\n{env_path.read_text()}")


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

    ADDITIONAL_AUTH_FIELDS = ("USERNAME", "PASSWORD")
    ADDITIONAL_SENSITIVE_AUTH_FIELDS = ("USERNAME", "PASSWORD")

    def __init__(self, profile=None, profile_auth_type=None):
        tool_dir = resolve_tool_dir(self.DIST_NAME)
        _migrate_legacy_profiles(tool_dir.name)
        super().__init__(
            tool_dir=tool_dir,
            profile=profile,
            profile_auth_type=profile_auth_type,
        )

    @property
    def auth_type(self):
        return self._get(self.PROFILE_AUTH_TYPE_FIELD)

    @property
    def graph_version(self) -> str:
        return self._get("FACEBOOK_GRAPH_VERSION") or DEFAULT_GRAPH_VERSION

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
        return self.get_browser().has_session()

    def get_missing_credentials(self) -> list[str]:
        if self.auth_type == API_AUTH_TYPE:
            required = ("CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN")
            return [field for field in required if not self._get(field)]
        return [] if self.get_browser().has_session() else ["browser_session"]

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
        if not browser.has_session():
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
