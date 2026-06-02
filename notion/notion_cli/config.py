"""Configuration management for Notion CLI."""
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Notion CLI configuration (bearer-token auth)."""

    DIST_NAME = "notion-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DEFAULT_BASE_URL = "https://api.notion.com/v1"
    CUSTOM_REQUIRED_FIELDS = ["NOTION_API_TOKEN"]
    CUSTOM_SENSITIVE_FIELDS = ["NOTION_API_TOKEN"]
    ROOT_CONFIG_FIELDS = ("NOTION_API_VERSION",)
    SECRET_NAME_OVERRIDES = {
        "NOTION_API_TOKEN": "notion-api-token",
    }

    LOGIN_INSTRUCTIONS = (
        "To get your Notion integration token:\n"
        "  1. Go to https://www.notion.so/my-integrations\n"
        "  2. Create a new internal integration\n"
        "  3. Copy the 'Internal Integration Secret'\n"
        "  4. Share your database/pages with the integration"
    )

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def api_token(self) -> Optional[str]:
        return self._get("NOTION_API_TOKEN")

    @property
    def api_version(self) -> str:
        return self._get("NOTION_API_VERSION") or "2025-09-03"

    def test_connection(self) -> Optional[dict]:
        """Verify the integration token by fetching the current bot user."""
        from .client import NotionClient, ClientError
        try:
            client = NotionClient(config=self)
            user = client.get_current_user()
            return {
                "api_test": "passed",
                "bot_id": user.get("id", ""),
                "bot_name": user.get("name", ""),
                "type": user.get("type", ""),
                "workspace": user.get("bot", {}).get("workspace_name", ""),
                "api_version": self.api_version,
            }
        except ClientError as e:
            return {"api_test": f"failed: {e}"}


_configs: dict = {}


def get_config(profile=None) -> Config:
    """Get or create a config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
