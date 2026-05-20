"""Configuration management for n8n CLI Tool Node Converter."""
import os
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.repo_paths import find_cli_tools_repo_root
from dotenv import set_key


class Config(BaseConfig):
    """Configuration manager - stores CLI tools directory and output directory paths."""

    DIST_NAME = "n8n-cli-tool-node-converter-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS = []
    CUSTOM_ALL_FIELDS = ["N8N_CONVERTER_CLI_TOOLS_DIR", "N8N_CONVERTER_OUTPUT_DIR"]
    CUSTOM_EPHEMERAL_FIELDS = []

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )
        self._ensure_repo_default_env_stub()

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
        return Path(self.cli_tools_dir).is_dir()

    def get_missing_credentials(self) -> list[str]:
        """Get list of missing configuration."""
        missing = []
        if not Path(self.cli_tools_dir).is_dir():
            missing.append(f"CLI tools directory not found: {self.cli_tools_dir}")
        return missing

    def test_connection(self) -> dict:
        """Verify the converter can see the cli-tools monorepo."""
        if not Path(self.cli_tools_dir).is_dir():
            return {"api_test": f"failed: CLI tools directory not found: {self.cli_tools_dir}"}
        return {
            "api_test": "passed",
            "cli_tools_dir": self.cli_tools_dir,
            "output_dir": self.output_dir,
        }

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

    def _ensure_repo_default_env_stub(self) -> None:
        """Keep a repo-local default profile stub for compliance profile tests."""
        repo_env = self.tool_dir / ".env"
        if not repo_env.exists():
            repo_env.write_text("IS_DEFAULT_PROFILE=1\n")


# Global config instance - singleton pattern
_config: Optional[Config] = None


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None or profile is not None:
        _config = Config(profile=profile)
    return _config
