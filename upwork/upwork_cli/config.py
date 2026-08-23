"""Configuration management for Upwork CLI.

Multi-auth: a browser session (profile read/update, currently disabled behind
Upwork's Cloudflare challenge) and an OAuth2 authorization-code credential for
the official GraphQL API used by the ``jobs`` command group.

Uses BaseConfig from cli_tools_shared for profile-aware env loading. Browser
automation lives in browser.py; the GraphQL transport lives in graphql.py.
"""

from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType

# OAuth2 endpoints (Upwork). The GraphQL API is served from api.upwork.com; the
# OAuth authorize/token endpoints live on www.upwork.com.
UPWORK_OAUTH_AUTH_URL = "https://www.upwork.com/ab/account-security/oauth2/authorize"
UPWORK_OAUTH_TOKEN_URL = "https://www.upwork.com/api/v3/oauth2/token"
UPWORK_GRAPHQL_URL = "https://api.upwork.com/graphql"

# Localhost callback used for the OAuth authorization-code redirect. Overridable
# per profile via the REDIRECT_URI env value or OAUTH_REDIRECT_URI on the class.
# This EXACT value is registered on the Upwork developer app.
DEFAULT_REDIRECT_URI = "http://localhost:8765/callback"

# Lightweight GraphQL probe for `auth status` — resolves the authenticated user's
# id, which any valid token can read.
_AUTH_TEST_QUERY = "query { user { id } }"


class Config(BaseConfig):
    """Configuration for Upwork — extends BaseConfig for shared auth/profile support."""

    DIST_NAME = "upwork-cli"

    CREDENTIAL_TYPES = [
        CredentialType.BROWSER_SESSION,
        CredentialType.OAUTH_AUTHORIZATION_CODE,
    ]
    DEFAULT_BASE_URL = "https://www.upwork.com"

    # OAuth 2.0 authorization-code configuration. create_auth_app auto-detects
    # OAUTH_AUTH_URL + OAUTH_TOKEN_URL and wires the built-in browser OAuth flow.
    OAUTH_AUTH_URL = UPWORK_OAUTH_AUTH_URL
    OAUTH_TOKEN_URL = UPWORK_OAUTH_TOKEN_URL
    OAUTH_SCOPES: list = []  # Upwork grants scopes at the developer-app level.
    OAUTH_TOKEN_AUTH = "body"  # client_id/client_secret in the token POST body.
    OAUTH_REDIRECT_URI = DEFAULT_REDIRECT_URI

    AUTH_SETUP_INSTRUCTIONS = (
        "Before logging in for the Upwork GraphQL API:\n"
        "  1. Create an API key at https://www.upwork.com/developer/keys/apply\n"
        f"  2. Register the redirect URI EXACTLY as: {DEFAULT_REDIRECT_URI}\n"
        "     (override with REDIRECT_URI in the profile env if you registered a different one)\n"
        "  3. Enter the app's Client ID as CLIENT_ID and Client Secret as CLIENT_SECRET."
    )

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    # ==================== GraphQL / OAuth API ====================

    @property
    def graphql_url(self) -> str:
        """Upwork GraphQL endpoint (overridable via GRAPHQL_URL env)."""
        return self._get("GRAPHQL_URL") or UPWORK_GRAPHQL_URL

    def has_api_credentials(self) -> bool:
        """True when OAuth API credentials are configured (ignores browser session).

        Dual-auth CLIs must not gate API commands on ``has_credentials()`` (AND
        semantics), which would block the GraphQL API when no browser session
        exists.
        """
        return bool(self.client_id and self.client_secret and self.access_token)

    def test_connection(self) -> dict:
        """Validate the OAuth credential by making a lightweight GraphQL call.

        Distinguishes not-configured (no OAuth app credentials) from
        configured-but-invalid (credentials present but the API rejects them).
        Powers the OAuth branch of ``auth status``.
        """
        if not (self.client_id and self.client_secret):
            return {"api_test": "failed: OAuth app credentials not configured"}
        if not self.access_token:
            return {
                "api_test": "failed: no access token — run 'upwork auth login -c oauth_authorization_code'"
            }

        from .graphql import UpworkGraphQLClient

        try:
            data = UpworkGraphQLClient(self).execute(
                _AUTH_TEST_QUERY, operation_name="user"
            )
        except Exception as exc:  # noqa: BLE001 — surface the reason as status text
            return {"api_test": f"failed: {exc}"}

        user = data.get("user") if isinstance(data, dict) else None
        user_id = user.get("id") if isinstance(user, dict) else None
        result = {"api_test": "passed"}
        if user_id is not None:
            result["user_id"] = user_id
        return result

    # ==================== Browser Session (unchanged) ====================

    @property
    def headless(self) -> bool:
        val = self._get("HEADLESS")
        return val is None or val.lower() == "true"

    def get_browser(self):
        """Return the BrowserAutomation subclass for this CLI."""
        from .browser import UpworkBrowser
        return UpworkBrowser(self)


# Singleton pattern for config (per profile)
_configs: dict = {}


def get_config(profile=None) -> Config:
    """Get or create config instance for a profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
