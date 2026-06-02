"""Configuration management for Google Lighthouse CLI wrapper."""

import os
import shutil
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from dotenv import set_key


class Config(BaseConfig):
    """Configuration manager for Google Lighthouse CLI wrapper."""

    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS = []
    CUSTOM_ALL_FIELDS = ["CLI_COMMAND", "CLI_PATH", "LIGHTHOUSE_NPM_PACKAGE", "GOOGLE_LIGHTHOUSE_DATA_DIR"]
    CUSTOM_EPHEMERAL_FIELDS = []
    DIST_NAME = "google-lighthouse-cli"

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def cli_command(self) -> str:
        """Get the executable used to launch the official npm Lighthouse package."""
        return os.getenv("CLI_COMMAND", "npx")

    @property
    def lighthouse_package(self) -> str:
        """Get the npm package spec for Google's Lighthouse CLI."""
        return os.getenv("LIGHTHOUSE_NPM_PACKAGE", "lighthouse@13.2.0")

    @property
    def cli_path(self) -> Optional[str]:
        """Get optional full path to CLI executable."""
        return os.getenv("CLI_PATH")

    @property
    def data_dir(self) -> Path:
        """Get the directory used to store audit artifacts and summaries."""
        configured = os.getenv("GOOGLE_LIGHTHOUSE_DATA_DIR")
        if configured is not None:
            return Path(configured).expanduser()
        return Path.home() / "Library" / "Application Support" / "cli-tools" / "google-lighthouse" / "audits"

    def get_cli_command(self) -> list[str]:
        """Get the command prefix for the official Google Lighthouse CLI."""
        if self.cli_path:
            return [self.cli_path]
        return [self.cli_command, "--yes", "--package", self.lighthouse_package, "lighthouse"]

    def get_cli_executable(self) -> str:
        """Get the executable path used to launch Lighthouse."""
        return self.get_cli_command()[0]

    def is_cli_available(self) -> bool:
        """Check if the underlying CLI is available in PATH."""
        return shutil.which(self.get_cli_executable()) is not None

    def get_cli_version(self) -> Optional[str]:
        """Get the version of the underlying CLI (if available)."""
        import subprocess

        try:
            result = subprocess.run(
                self.get_cli_command() + ["--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        return None

    def test_connection(self) -> dict:
        """Validate the local Lighthouse launcher configuration."""
        if not self.is_cli_available():
            return {"api_test": f"failed: underlying CLI '{self.get_cli_executable()}' not found"}
        return {"api_test": "passed"}

    def save_setting(self, key: str, value: str):
        """Save a setting to the .env file and update environment."""
        set_key(self.env_file_path, key, value)
        # Also update os.environ so subsequent reads get the new value
        os.environ[key] = value

    def clear_settings(self):
        """Clear all settings from .env file and environment."""
        # Track keys before clearing file
        if self.env_file_path.exists():
            # Read existing keys to clear from os.environ
            from dotenv import dotenv_values
            existing = dotenv_values(self.env_file_path)
            for key in existing:
                os.environ.pop(key, None)
            self.env_file_path.write_text("")


# Global config instance - singleton pattern
_config: Optional[Config] = None


def get_config(profile=None) -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None or profile is not None:
        _config = Config(profile=profile)
    return _config
