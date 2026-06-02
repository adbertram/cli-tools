"""Configuration management for CodexSessions CLI wrapper."""
import os
import shutil
from pathlib import Path
from typing import Optional

from dotenv import set_key
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration manager for CodexSessions CLI wrapper."""

    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DIST_NAME = "codex-sessions-cli"

    def __init__(self, profile=None):
        """Initialize configuration by loading from .env file."""
        super().__init__(tool_dir=resolve_tool_dir(self.DIST_NAME), profile=profile)

    @property
    def cli_command(self) -> str:
        """Get the underlying CLI command name."""
        return os.getenv("CLI_COMMAND", "codex")

    @property
    def cli_path(self) -> Optional[str]:
        """Get optional full path to CLI executable."""
        return os.getenv("CLI_PATH")

    @property
    def codex_home(self) -> Path:
        """Get the Codex home directory containing sessions and config."""
        configured = os.getenv("CODEX_SESSIONS_CODEX_HOME") or os.getenv("CODEX_HOME")
        if configured:
            return Path(configured).expanduser()
        return Path.home() / ".codex"

    def test_connection(self) -> dict:
        """Verify the local Codex transcript store is readable."""
        codex_home = self.codex_home
        sessions_dir = codex_home / "sessions"
        exists = codex_home.exists()
        return {
            "api_test": "passed" if exists else f"failed: {codex_home} does not exist",
            "codex_home": str(codex_home),
            "sessions_dir": str(sessions_dir),
            "cli_command": self.cli_command,
            "cli_available": self.is_cli_available(),
            "cli_version": self.get_cli_version(),
        }

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
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            return None
        return None

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
