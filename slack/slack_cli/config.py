"""Configuration management for Slack CLI."""
from pathlib import Path
from typing import Optional
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Slack CLI configuration - extends BaseConfig for profile support."""

    DIST_NAME = "slack-cli"

    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS = ['ACCESS_TOKEN']
    CUSTOM_ALL_FIELDS = ['ACCESS_TOKEN', 'REFRESH_TOKEN', 'TOKEN_EXPIRES_AT',
                         'CLIENT_ID', 'CLIENT_SECRET', 'SLACK_TEAM_ID']
    CUSTOM_SENSITIVE_FIELDS = ['ACCESS_TOKEN', 'REFRESH_TOKEN', 'CLIENT_SECRET']
    CUSTOM_EPHEMERAL_FIELDS = ['ACCESS_TOKEN', 'REFRESH_TOKEN', 'TOKEN_EXPIRES_AT']
    CUSTOM_LOGIN_PROMPTS = []  # login_handler handles all credential acquisition

    DEFAULT_BASE_URL = "https://slack.com/api"

    # OAuth scopes for bot tokens (xoxb-)
    BOT_SCOPES = [
        "calls:read",
        "calls:write",
        "channels:history",
        "channels:join",
        "channels:manage",
        "channels:read",
        "channels:write.invites",
        "channels:write.topic",
        "chat:write",
        "files:read",
        "files:write",
        "groups:history",
        "groups:read",
        "groups:write",
        "im:history",
        "im:read",
        "im:write",
        "mpim:history",
        "mpim:read",
        "search:read.files",
        "search:read.public",
        "search:read.users",
        "team:read",
        "users.profile:read",
        "users:read",
        "users:read.email",
    ]

    # OAuth scopes for user tokens (xoxp-)
    USER_SCOPES = [
        "calls:read",
        "calls:write",
        "channels:history",
        "channels:read",
        "channels:write.invites",
        "channels:write.topic",
        "chat:write",
        "files:read",
        "files:write",
        "groups:history",
        "groups:read",
        "groups:write",
        "im:history",
        "im:read",
        "im:write",
        "mpim:history",
        "mpim:read",
        "search:read",
        "team:read",
        "users.profile:read",
        "users:read",
        "users:read.email",
    ]

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def storage_dir(self) -> Path:
        """Storage directory for cache and runtime data."""
        return self.tool_dir

    def get_browser(self):
        """Return browser automation instance for Slack."""
        from .browser import SlackBrowser
        return SlackBrowser(self)

    def test_connection(self) -> dict:
        """Test Slack API connectivity using stored ACCESS_TOKEN."""
        import requests
        token = self._get("ACCESS_TOKEN")
        if not token:
            return {"api_test": "failed: no ACCESS_TOKEN"}
        try:
            resp = requests.get(
                f"{self.base_url}/auth.test",
                headers={"Authorization": f"Bearer {token}"},
                cookies={"d": self._get("REFRESH_TOKEN") or ""},
                timeout=10,
            )
            data = resp.json()
            if data.get("ok"):
                return {
                    "api_test": "passed",
                    "team": data.get("team"),
                    "user": data.get("user"),
                    "team_id": data.get("team_id"),
                }
            return {"api_test": f"failed: {data.get('error', 'unknown')}"}
        except Exception as e:
            return {"api_test": f"failed: {str(e)}"}


_configs: dict = {}


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create a config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]


def reset_config():
    """Reset the global config instances (useful for testing)."""
    global _configs
    _configs = {}
