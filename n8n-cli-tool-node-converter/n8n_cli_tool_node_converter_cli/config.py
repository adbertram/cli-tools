"""Configuration management for n8n CLI Tool Node Converter."""
import os
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from dotenv import set_key


class Config(BaseConfig):
    """Configuration manager - stores CLI tools directory and output directory paths."""

    CREDENTIAL_TYPES: list = []  # custom field set; managed by this subclass
    DIST_NAME = "n8n-cli-tool-node-converter-cli"

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def cli_tools_dir(self) -> str:
        """Get CLI tools directory path."""
        return os.getenv(
            "N8N_CONVERTER_CLI_TOOLS_DIR",
            str(Path.home() / "Dropbox" / "GitRepos" / "cli-tools"),
        )

    @property
    def output_dir(self) -> str:
        """Get output directory for generated n8n node packages."""
        return os.getenv(
            "N8N_CONVERTER_OUTPUT_DIR",
            str(Path.home() / "Dropbox" / "GitRepos" / "n8n-nodes"),
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


def get_config() -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config
