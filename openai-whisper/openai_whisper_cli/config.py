"""Configuration management for Whisper CLI wrapper."""
import os
import shutil
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from dotenv import set_key


class Config(BaseConfig):
    """Configuration manager for OpenAI Whisper CLI wrapper."""

    CREDENTIAL_TYPES: list = []  # custom field set; managed by this subclass
    DIST_NAME = "openai-whisper-cli"

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def cli_command(self) -> str:
        """Get the underlying CLI command name."""
        return os.getenv("WHISPER_CLI_COMMAND", "whisper")

    @property
    def cli_path(self) -> Optional[str]:
        """Get optional full path to CLI executable."""
        return os.getenv("WHISPER_CLI_PATH")

    def get_cli_executable(self) -> str:
        """Get the CLI executable path, falling back to command name."""
        if self.cli_path:
            return self.cli_path
        return self.cli_command

    @property
    def default_model(self) -> str:
        """Default Whisper model when the --model flag is not provided.

        Sourced from OPENAI_WHISPER_MODEL; falls back to 'turbo' (the engine
        default and prior hardcoded value).
        """
        return os.getenv("OPENAI_WHISPER_MODEL", "turbo")

    @property
    def default_initial_prompt(self) -> Optional[str]:
        """Default vocabulary-biasing initial prompt when --initial-prompt is omitted.

        Sourced from OPENAI_WHISPER_INITIAL_PROMPT. Unset by default; an empty
        or whitespace-only value is treated as no prompt.
        """
        value = os.getenv("OPENAI_WHISPER_INITIAL_PROMPT")
        if value is not None and value.strip() == "":
            return None
        return value

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


def get_config() -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config
