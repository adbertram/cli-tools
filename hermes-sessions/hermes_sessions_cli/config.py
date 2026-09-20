"""Configuration for the Hermes Sessions CLI.

The CLI reads the Hermes Agent state store (`state.db`) under the Hermes home
directory. There is no remote credential and no wrapped binary; `auth status`
reports whether that local store is readable.
"""
import os
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values

from cli_tools_shared.config import (
    BaseConfig,
    config_env_path_for_tool,
    env_path_for_profile,
    resolve_tool_dir,
)
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration manager for the Hermes Sessions CLI."""

    DIST_NAME = "hermes-sessions-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    ROOT_CONFIG_FIELDS = ("HERMES_HOME",)

    def __init__(self, profile: Optional[str] = None):
        """Resolve configuration without bootstrapping files or profiles.

        ``BaseConfig.__init__`` creates a default profile on first use. That is
        appropriate for credential-owning CLIs, but this local state reader is
        read-only: even constructing its config must leave the filesystem
        unchanged. Keep the small set of attributes expected by the shared
        command registry while loading the optional root ``.env`` read-only.
        """
        self.tool_dir = resolve_tool_dir(self.DIST_NAME)
        self._tool_name = self.tool_dir.name
        self.profile = profile
        self.profile_auth_type = None
        self.config_env_file_path = config_env_path_for_tool(self._tool_name)
        self.env_file_path = env_path_for_profile(
            self._tool_name, profile or "default"
        )
        self._root_values = {}
        if self.config_env_file_path.is_file():
            try:
                self._root_values = {
                    key: value
                    for key, value in dotenv_values(
                        self.config_env_file_path
                    ).items()
                    if value is not None
                }
            except (OSError, UnicodeError):
                # An unreadable optional config is equivalent to no override;
                # the explicit environment and ~/.hermes default still work.
                self._root_values = {}

    def _get(self, name: str) -> Optional[str]:
        """Read an environment/root-config value without mutating process state."""
        value = os.environ.get(name)
        if value is None:
            value = self._root_values.get(name)
        return value if value else None

    @property
    def hermes_home(self) -> Path:
        """Resolve the Hermes home directory.

        Precedence mirrors Hermes' own `get_hermes_home()`, with one CLI-scoped
        override in front so this tool can be pointed at a specific Hermes
        profile home without changing Hermes' own environment:
        `HERMES_SESSIONS_HERMES_HOME`, then `HERMES_HOME` (environment or this
        tool's config `.env`), then `~/.hermes`. A blank value is treated as
        unset so it never resolves to the current directory.
        """
        for name in ("HERMES_SESSIONS_HERMES_HOME", "HERMES_HOME"):
            configured = self._get(name)
            if configured and configured.strip():
                return Path(configured.strip()).expanduser()
        return Path.home() / ".hermes"

    @property
    def state_db_path(self) -> Path:
        """Path to the Hermes SQLite state store."""
        return self.hermes_home / "state.db"

    def test_connection(self) -> dict:
        """Verify the local Hermes state store is readable."""
        state_db = self.state_db_path
        readable = state_db.is_file() and os.access(state_db, os.R_OK)
        return {
            "api_test": "passed" if readable else f"failed: {state_db} is not a readable file",
            "hermes_home": str(self.hermes_home),
            "state_db": str(state_db),
            "state_db_readable": readable,
        }

    def save_setting(self, key: str, value: str):
        """Reject writes: hermes-sessions has no configuration mutations."""
        raise RuntimeError("hermes-sessions configuration is read-only")

    def clear_settings(self):
        """Reject writes: hermes-sessions has no configuration mutations."""
        raise RuntimeError("hermes-sessions configuration is read-only")


_config: Optional[Config] = None


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None or profile is not None:
        _config = Config(profile=profile)
    return _config
