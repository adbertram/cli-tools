"""Configuration management for {{Name}} CLI wrapper."""

import shutil
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir


class Config(BaseConfig):
    """Configuration manager for {{Name}} CLI wrapper."""

    DIST_NAME = "{{name}}-cli"
    CREDENTIAL_TYPES = []
    DEFAULT_BASE_URL = ""
    ROOT_CONFIG_FIELDS = ("CLI_COMMAND", "CLI_PATH")

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def storage_dir(self) -> Path:
        """Profile-aware storage directory for wrapper runtime state."""
        return self.get_profile_data_dir()

    @property
    def cli_command(self) -> str:
        """Get the underlying CLI command name."""
        return self._get("CLI_COMMAND") or "{{cli_command}}"

    @property
    def cli_path(self) -> Optional[str]:
        """Get optional full path to CLI executable."""
        return self._get("CLI_PATH")

    def get_cli_executable(self) -> str:
        """Get the CLI executable path, falling back to command name."""
        if self.cli_path:
            return self.cli_path
        return self.cli_command

    def is_cli_available(self) -> bool:
        """Check if the underlying CLI is available in PATH."""
        return shutil.which(self.get_cli_executable()) is not None

    def get_cli_version(self) -> Optional[str]:
        """Get the version of the underlying CLI (if available)."""
        import subprocess

        try:
            result = subprocess.run(
                [self.get_cli_executable(), "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                output = result.stdout.strip() or result.stderr.strip()
                return output or None
        except subprocess.SubprocessError:
            return None
        return None

    def save_setting(self, key: str, value: str):
        """Save a setting to the .env file and update environment."""
        self._set(key.upper(), value)

    def clear_settings(self):
        """Clear all settings from .env file and environment."""
        self._clear("CLI_COMMAND")
        self._clear("CLI_PATH")

_config: Optional[Config] = None


def get_config(profile=None) -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config
