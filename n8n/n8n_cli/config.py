"""Configuration management for n8n CLI."""
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.repo_paths import find_cli_tools_repo_root


class Config(BaseConfig):
    """Configuration manager for n8n CLI - extends BaseConfig with profile support."""

    DIST_NAME = "n8n-cli"
    CREDENTIAL_TYPES = [CredentialType.API_KEY]
    DEFAULT_BASE_URL = "http://localhost:5678/api/v1"
    ADDITIONAL_AUTH_FIELDS = ("PASSWORD",)
    ADDITIONAL_SENSITIVE_AUTH_FIELDS = ("PASSWORD",)

    def __init__(self, profile=None):
        """Initialize configuration by loading profile-aware .env file."""
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def cli_tools_dir(self) -> str:
        """Get CLI tools directory path."""
        return self._get("N8N_CONVERTER_CLI_TOOLS_DIR") or str(find_cli_tools_repo_root())

    @property
    def output_dir(self) -> str:
        """Get output directory for generated n8n node packages."""
        return self._get("N8N_CONVERTER_OUTPUT_DIR") or str(
            self.get_profile_data_dir() / "n8n-nodes"
        )

    def save_cli_tools_dir(self, path: str):
        """Save CLI tools directory path to .env."""
        self._set("N8N_CONVERTER_CLI_TOOLS_DIR", path)

    def save_output_dir(self, path: str):
        """Save output directory path to .env."""
        self._set("N8N_CONVERTER_OUTPUT_DIR", path)

    def test_connection(self):
        """Test n8n API connectivity."""
        from .n8n_api import N8nApiClient, N8nApiError
        try:
            client = N8nApiClient(base_url=self.base_url, api_key=self.api_key)
            client._request("GET", "/executions", params={"limit": 1})
            return {"api_test": "passed"}
        except N8nApiError as e:
            return {"api_test": f"failed: {e}"}


def get_config(profile=None) -> Config:
    """Get a Config instance for the given profile."""
    return Config(profile=profile)
