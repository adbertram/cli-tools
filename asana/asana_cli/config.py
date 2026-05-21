"""Configuration management for Asana CLI."""
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Asana CLI configuration (Personal Access Token auth)."""

    DIST_NAME = "asana-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DEFAULT_BASE_URL = "https://app.asana.com/api/1.0"
    CUSTOM_REQUIRED_FIELDS = ["ASANA_PAT", "ASANA_WORKSPACE_ID"]
    CUSTOM_ALL_FIELDS = [
        "ASANA_PAT",
        "ASANA_WORKSPACE_ID",
        "PODIO_CLIENT_SECRET",
        "ASANA_CLIENT_SECRET",
        "REVIEW_AGENT_COORDINATOR_AGENT_DIRECTLINE_SECRET",
        "DEVELOPMENTAL_REVIEWER_EDITOR_DIRECTLINE_SECRET",
        "AZURE_CLIENT_SECRET",
        "DOCUMENT_INTELLIGENCE_API_KEY",
        "M365_SDK_CLIENT_SECRET",
    ]
    CUSTOM_SENSITIVE_FIELDS = [
        "ASANA_PAT",
        "PODIO_CLIENT_SECRET",
        "ASANA_CLIENT_SECRET",
        "REVIEW_AGENT_COORDINATOR_AGENT_DIRECTLINE_SECRET",
        "DEVELOPMENTAL_REVIEWER_EDITOR_DIRECTLINE_SECRET",
        "AZURE_CLIENT_SECRET",
        "DOCUMENT_INTELLIGENCE_API_KEY",
        "M365_SDK_CLIENT_SECRET",
    ]

    LOGIN_INSTRUCTIONS = (
        "To get your Asana Personal Access Token:\n"
        "  1. Go to https://app.asana.com/0/my-apps\n"
        "  2. Click '+ Create new token' under Personal access tokens\n"
        "  3. Copy the generated token"
    )

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    # ---- Compatibility shims for existing client.py code ----

    @property
    def pat(self) -> Optional[str]:
        return self._get("ASANA_PAT")

    @property
    def workspace_id(self) -> Optional[str]:
        return self._get("ASANA_WORKSPACE_ID")

    def test_connection(self) -> Optional[dict]:
        """Verify the PAT by fetching the current user."""
        from .client import AsanaClient, ClientError
        try:
            client = AsanaClient(config=self)
            user = client.get_user("me")
            return {
                "api_test": "passed",
                "user_id": user.get("gid", ""),
                "name": user.get("name", ""),
                "email": user.get("email", ""),
                "workspace_id": self.workspace_id or "",
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
