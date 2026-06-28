"""Configuration management for ClaudeCodeSessions CLI wrapper."""
import os
import shutil
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from dotenv import set_key


class Config(BaseConfig):
    """Configuration manager for ClaudeCodeSessions CLI wrapper."""

    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DIST_NAME = "claude-code-sessions-cli"

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def cli_command(self) -> str:
        """Get the underlying CLI command name."""
        return os.getenv("CLAUDE_CODE_SESSIONS_CLI_COMMAND", "claude")

    @property
    def cli_path(self) -> Optional[str]:
        """Get optional full path to CLI executable."""
        return os.getenv("CLAUDE_CODE_SESSIONS_CLI_PATH")

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
            pass
        return None

    def test_connection(self) -> dict:
        """Verify the local Claude transcript store is readable."""
        claude_home = os.getenv("CLAUDE_CODE_SESSIONS_CLAUDE_HOME") or os.getenv("CLAUDE_HOME")
        claude_dir = Path(claude_home).expanduser() if claude_home else Path.home() / ".claude"
        projects_dir = claude_dir / "projects"
        exists = claude_dir.exists()
        return {
            "api_test": "passed" if exists else f"failed: {claude_dir} does not exist",
            "claude_dir": str(claude_dir),
            "projects_dir": str(projects_dir),
            "cli_command": self.cli_command,
            "cli_available": self.is_cli_available(),
            "cli_version": self.get_cli_version(),
        }

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


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None or profile is not None:
        _config = Config(profile=profile)
    return _config
