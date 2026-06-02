"""Configuration management for Kick CLI."""
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


# Auth0 configuration for kick.co (built-in defaults, not user-provided)
AUTH0_DOMAIN = "auth.kick.co"
AUTH0_CLIENT_ID = "nxwpRHdJfzjF335hJIHSDPgG0y16fRTl"
AUTH0_AUDIENCE = "https://use.kick.co"  # API identifier


class Config(BaseConfig):
    """Kick CLI configuration - OAuth via Auth0 PKCE."""

    DIST_NAME = "kick-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DEFAULT_BASE_URL = "https://use.kick.co"

    # Tokens acquired via Auth0 PKCE flow (no static credentials prompted)
    CUSTOM_REQUIRED_FIELDS = ["KICK_ACCESS_TOKEN"]
    CUSTOM_ALL_FIELDS = [
        "KICK_ACCESS_TOKEN",
        "KICK_REFRESH_TOKEN",
        "KICK_TOKEN_EXPIRES_AT",
        "KICK_CALLBACK_URL",
        "KICK_BASE_URL",
    ]
    CUSTOM_LOGIN_PROMPTS = []  # No static prompts — login_handler does PKCE flow
    CUSTOM_EPHEMERAL_FIELDS = [
        "KICK_ACCESS_TOKEN",
        "KICK_REFRESH_TOKEN",
        "KICK_TOKEN_EXPIRES_AT",
        "KICK_CALLBACK_URL",
    ]
    CUSTOM_SENSITIVE_FIELDS = [
        "KICK_ACCESS_TOKEN",
        "KICK_REFRESH_TOKEN",
        "KICK_CALLBACK_URL",
    ]

    LOGIN_INSTRUCTIONS = (
        "Kick uses Auth0 PKCE OAuth. A browser window will open for sign-in.\n"
        "After signing in, copy the full callback URL (starts with https://use.kick.co/?code=...)\n"
        "and paste it when prompted."
    )

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    # ---- Compatibility shims for existing client.py code ----

    @property
    def auth0_domain(self) -> str:
        return self._get("KICK_AUTH0_DOMAIN") or AUTH0_DOMAIN

    @property
    def auth0_client_id(self) -> str:
        return self._get("KICK_AUTH0_CLIENT_ID") or AUTH0_CLIENT_ID

    @property
    def auth0_audience(self) -> str:
        return self._get("KICK_AUTH0_AUDIENCE") or AUTH0_AUDIENCE

    @property
    def access_token(self) -> Optional[str]:
        return self._get("KICK_ACCESS_TOKEN")

    @property
    def refresh_token(self) -> Optional[str]:
        return self._get("KICK_REFRESH_TOKEN")

    @property
    def token_expires_at(self) -> Optional[str]:
        return self._get("KICK_TOKEN_EXPIRES_AT")

    @property
    def base_url(self) -> str:
        return self._get("KICK_BASE_URL") or self.DEFAULT_BASE_URL

    @property
    def auth_url(self) -> str:
        return f"https://{self.auth0_domain}"

    @property
    def api_key(self) -> Optional[str]:
        # Legacy hook used by client.py _update_headers fallback
        return None

    def save_tokens(self, access_token: str, refresh_token: Optional[str], expires_at: str):
        """Save OAuth tokens via BaseConfig._set."""
        self._set("KICK_ACCESS_TOKEN", access_token)
        if refresh_token:
            self._set("KICK_REFRESH_TOKEN", refresh_token)
        self._set("KICK_TOKEN_EXPIRES_AT", expires_at)

    def test_connection(self) -> Optional[dict]:
        """Verify credentials by listing workspaces."""
        try:
            from .client import KickClient
            client = KickClient(config=self)
            workspaces = client.get_workspaces()
            return {
                "api_test": "passed",
                "workspace_count": len(workspaces),
            }
        except Exception as e:
            return {"api_test": f"failed: {e}"}


_configs: dict = {}


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create a config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]


def reset_config():
    """Reset all config instances (for testing)."""
    global _configs
    _configs = {}
