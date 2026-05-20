"""Configuration management for n8n Node."""
import os
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.repo_paths import find_cli_tools_repo_root
from dotenv import set_key


class Config(BaseConfig):
    """Configuration manager - stores CLI tools directory and output directory paths."""

    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DIST_NAME = "n8n-node-cli"
    CUSTOM_REQUIRED_FIELDS = ["N8N_BASE", "N8N_API_KEY"]
    CUSTOM_ALL_FIELDS = [
        "N8N_CONVERTER_CLI_TOOLS_DIR",
        "N8N_CONVERTER_OUTPUT_DIR",
        "N8N_BASE",
        "N8N_API_KEY",
        "N8N_EMAIL",
        "N8N_PASSWORD",
        "N8N_SSH_HOST",
    ]
    CUSTOM_LOGIN_PROMPTS = [
        ("N8N_BASE", "n8n API base URL", False),
        ("N8N_API_KEY", "n8n API key", True),
        ("N8N_EMAIL", "n8n UI email", False),
        ("N8N_PASSWORD", "n8n UI password", True),
        ("N8N_SSH_HOST", "n8n SSH host", False),
    ]
    CUSTOM_SENSITIVE_FIELDS = ["N8N_API_KEY", "N8N_PASSWORD"]

    def __init__(self, profile: Optional[str] = None):
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

    def has_credentials(self) -> bool:
        """Check if required configuration is available (paths exist)."""
        return super().has_credentials() and Path(self.cli_tools_dir).is_dir()

    def get_missing_credentials(self) -> list[str]:
        """Get list of missing configuration."""
        missing = []
        if not Path(self.cli_tools_dir).is_dir():
            missing.append(f"CLI tools directory not found: {self.cli_tools_dir}")
        return missing + super().get_missing_credentials()

    def test_connection(self) -> dict:
        """Verify the n8n API key against the configured server."""
        from .n8n_api import N8nApiClient, N8nApiError

        try:
            client = N8nApiClient(base_url=self._get("N8N_BASE"), api_key=self._get("N8N_API_KEY"))
            client._request("GET", "/executions", params={"limit": 1})
            return {"api_test": "passed"}
        except N8nApiError as exc:
            return {"api_test": f"failed: {exc}"}

    def save_cli_tools_dir(self, path: str):
        """Save CLI tools directory path to .env and update environment."""
        set_key(str(self.env_file_path), "N8N_CONVERTER_CLI_TOOLS_DIR", path)
        os.environ["N8N_CONVERTER_CLI_TOOLS_DIR"] = path

    def save_output_dir(self, path: str):
        """Save output directory path to .env and update environment."""
        set_key(str(self.env_file_path), "N8N_CONVERTER_OUTPUT_DIR", path)
        os.environ["N8N_CONVERTER_OUTPUT_DIR"] = path

    def clear_credentials(self):
        """Clear all configuration from .env file and environment."""
        set_key(str(self.env_file_path), "N8N_CONVERTER_CLI_TOOLS_DIR", "")
        set_key(str(self.env_file_path), "N8N_CONVERTER_OUTPUT_DIR", "")
        os.environ.pop("N8N_CONVERTER_CLI_TOOLS_DIR", None)
        os.environ.pop("N8N_CONVERTER_OUTPUT_DIR", None)


# Global config instance - singleton pattern
_config: Optional[Config] = None


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None or profile is not None:
        _config = Config(profile=profile)
    return _config
