"""Configuration management for {{Name}} CLI wrapper."""
import os
import shutil
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv, set_key


class Config:
    """Configuration manager for {{Name}} CLI wrapper."""

    def __init__(self):
        """Initialize configuration by loading from .env file."""
        config_dir = Path(__file__).resolve().parent.parent
        cli_env_path = config_dir / ".env"

        self.tool_dir = config_dir
        self.env_file_path = cli_env_path

        if cli_env_path.exists():
            load_dotenv(cli_env_path, override=True)
        else:
            cli_env_path.parent.mkdir(parents=True, exist_ok=True)
            cli_env_path.touch()

    @property
    def cli_command(self) -> str:
        """Get the underlying CLI command name."""
        return os.getenv("CLI_COMMAND", "{{cli_command}}")

    @property
    def cli_path(self) -> Optional[str]:
        """Get optional full path to CLI executable."""
        return os.getenv("CLI_PATH")

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
    if _config is None:
        _config = Config()
    return _config
