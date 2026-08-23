"""Configuration management for the DeepSeekSessions CLI wrapper."""
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from dotenv import set_key


class Config(BaseConfig):
    """Configuration manager for the DeepSeekSessions CLI wrapper."""

    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DIST_NAME = "deepseek-sessions-cli"

    def __init__(self, profile: Optional[str] = None):
        super().__init__(tool_dir=resolve_tool_dir(self.DIST_NAME), profile=profile)

    @property
    def cli_command(self) -> str:
        """Name of the underlying DeepSeek Harness CLI."""
        return os.getenv("DEEPSEEK_SESSIONS_CLI_COMMAND", "dsh")

    @property
    def cli_path(self) -> Optional[str]:
        """Optional full path to the dsh executable."""
        return os.getenv("DEEPSEEK_SESSIONS_CLI_PATH")

    @property
    def dsh_home(self) -> Path:
        """Resolve the DeepSeek Harness home directory.

        Mirrors the harness's own precedence in `@deepseek-ai/dsh-home-paths`:
        an explicit override first, then `$DSH_HOME`, then `~/.dsh`. A blank
        `$DSH_HOME` is treated as unset so it never resolves to the cwd.
        """
        for name in ("DEEPSEEK_SESSIONS_DSH_HOME", "DSH_HOME"):
            configured = os.getenv(name)
            if configured and configured.strip():
                return Path(configured.strip()).expanduser()
        return Path.home() / ".dsh"

    @property
    def sessions_dir(self) -> Path:
        """Root directory holding one subdirectory per project."""
        return self.dsh_home / "sessions"

    def get_cli_executable(self) -> str:
        """Path to the dsh executable, or its command name."""
        if self.cli_path:
            return self.cli_path
        return self.cli_command

    def is_cli_available(self) -> bool:
        """Whether the dsh executable resolves on PATH."""
        return shutil.which(self.get_cli_executable()) is not None

    def get_cli_version(self) -> Optional[str]:
        """Version reported by the dsh executable, when it is installed."""
        if not self.is_cli_available():
            return None
        result = subprocess.run(
            [self.get_cli_executable(), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def test_connection(self) -> dict:
        """Verify the local dsh session store is readable."""
        sessions_dir = self.sessions_dir
        exists = self.dsh_home.exists()
        return {
            "api_test": "passed" if exists else f"failed: {self.dsh_home} does not exist",
            "dsh_home": str(self.dsh_home),
            "sessions_dir": str(sessions_dir),
            "sessions_dir_exists": sessions_dir.exists(),
            "cli_command": self.cli_command,
            "cli_available": self.is_cli_available(),
            "cli_version": self.get_cli_version(),
        }

    def save_setting(self, key: str, value: str):
        """Save a setting to the .env file and update the environment."""
        set_key(self.env_file_path, key, value)
        os.environ[key] = value

    def clear_settings(self):
        """Clear all settings from the .env file and the environment."""
        if self.env_file_path.exists():
            from dotenv import dotenv_values

            for key in dotenv_values(self.env_file_path):
                os.environ.pop(key, None)
            self.env_file_path.write_text("")


_config: Optional[Config] = None


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None or profile is not None:
        _config = Config(profile=profile)
    return _config
