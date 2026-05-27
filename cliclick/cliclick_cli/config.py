"""Configuration management for Cliclick CLI wrapper."""
import os
import shutil
from typing import Optional

from cli_tools_shared.config import (
    BaseConfig,
    config_env_path_for_tool,
    list_env_files,
    resolve_tool_dir,
)
from dotenv import dotenv_values, set_key, unset_key


class Config(BaseConfig):
    """Configuration manager for Cliclick CLI wrapper."""

    DIST_NAME = "cliclick-cli"
    CREDENTIAL_TYPES: list = []
    ROOT_CONFIG_FIELDS = ("CLI_COMMAND", "CLI_PATH")

    def __init__(self, profile=None):
        """Initialize configuration."""
        tool_dir = resolve_tool_dir(self.DIST_NAME)
        self._migrate_legacy_profile_config(tool_dir.name)
        super().__init__(
            tool_dir=tool_dir,
            profile=profile,
        )

    def _migrate_legacy_profile_config(self, tool_name: str) -> None:
        """Move tool-wide config out of legacy auth profile env files."""
        config_path = config_env_path_for_tool(tool_name)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if not config_path.exists():
            config_path.touch()

        config_values = dotenv_values(config_path)
        legacy_to_generic = {
            "CLICLICK_CLI_COMMAND": "CLI_COMMAND",
            "CLICLICK_CLI_PATH": "CLI_PATH",
        }

        for legacy_key, generic_key in legacy_to_generic.items():
            value = config_values.get(legacy_key)
            if value and not config_values.get(generic_key):
                set_key(config_path, generic_key, value)
                config_values[generic_key] = value
            if value:
                unset_key(config_path, legacy_key)

        for env_file in list_env_files(tool_name):
            legacy_values = dotenv_values(env_file)
            for legacy_key, generic_key in legacy_to_generic.items():
                value = legacy_values.get(legacy_key)
                if value and not config_values.get(generic_key):
                    set_key(config_path, generic_key, value)
                    config_values[generic_key] = value
                if value:
                    unset_key(env_file, legacy_key)

    def _resolve_env_file(
        self,
        profile: Optional[str] = None,
        profile_auth_type: Optional[str] = None,
    ):
        """No-auth wrapper CLIs always load tool-wide config from the root .env."""
        del profile, profile_auth_type
        config_path = self.config_env_file_path
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if not config_path.exists():
            config_path.touch()

        config_values = dotenv_values(config_path)
        for env_file in list_env_files(self._tool_name):
            legacy_values = dotenv_values(env_file)
            for key in self.ROOT_CONFIG_FIELDS:
                value = legacy_values.get(key)
                if value and not config_values.get(key):
                    set_key(config_path, key, value)
                    config_values[key] = value

        return config_path

    @property
    def cli_command(self) -> str:
        """Get the underlying CLI command name."""
        return os.getenv("CLI_COMMAND", "cliclick")

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
        set_key(self.config_env_file_path, key, value)
        os.environ[key] = value

    def clear_settings(self):
        """Clear all settings from .env file and environment."""
        # Track keys before clearing file
        if self.config_env_file_path.exists():
            # Read existing keys to clear from os.environ
            existing = dotenv_values(self.config_env_file_path)
            for key in existing:
                os.environ.pop(key, None)
            self.config_env_file_path.write_text("")


# Global config instance - singleton pattern
_config: Optional[Config] = None


def get_config(profile=None) -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None or profile is not None:
        _config = Config(profile=profile)
    return _config
