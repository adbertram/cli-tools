"""Configuration management for the whisper.cpp CLI wrapper.

Resolves the underlying ``whisper-cli`` binary and the local ggml model. Env
var names mirror the ``openai-whisper`` CLI so the two wrappers are
drop-in swappable:

- ``WHISPER_CLI_PATH``    absolute path to the whisper.cpp binary (wins)
- ``WHISPER_CLI_COMMAND`` command name on PATH (default ``whisper-cli``)
- ``WHISPER_CPP_MODEL``   path to the ggml model file (default small.en)
- ``WHISPER_CPP_PROMPT``  default initial prompt for vocabulary biasing (unset)
"""

import os
import shutil
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir

DEFAULT_CLI_COMMAND = "whisper-cli"
DEFAULT_MODEL_PATH = (
    "~/.local/share/cli-tools/whisper/models/ggml-small.en.bin"
)


class Config(BaseConfig):
    """Configuration manager for the whisper.cpp CLI wrapper."""

    DIST_NAME = "whisper-cli"
    CREDENTIAL_TYPES: list = []  # local CLI, no auth
    DEFAULT_BASE_URL = ""
    ROOT_CONFIG_FIELDS = (
        "WHISPER_CLI_COMMAND",
        "WHISPER_CLI_PATH",
        "WHISPER_CPP_MODEL",
        "WHISPER_CPP_PROMPT",
    )

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def storage_dir(self) -> Path:
        """Profile-aware storage directory for wrapper runtime state."""
        return self.get_profile_data_dir()

    # ==================== Binary resolution ====================

    @property
    def cli_command(self) -> str:
        """Underlying whisper.cpp command name (default ``whisper-cli``)."""
        return os.getenv("WHISPER_CLI_COMMAND") or DEFAULT_CLI_COMMAND

    @property
    def cli_path(self) -> Optional[str]:
        """Optional absolute path to the whisper.cpp binary."""
        return os.getenv("WHISPER_CLI_PATH") or None

    def get_cli_executable(self) -> str:
        """Resolve the binary: explicit path wins, else command name."""
        if self.cli_path:
            return self.cli_path
        return self.cli_command

    def is_cli_available(self) -> bool:
        """True when the resolved binary is runnable.

        An explicit ``WHISPER_CLI_PATH`` is checked as a concrete file; a bare
        command name is resolved through PATH.
        """
        executable = self.get_cli_executable()
        if os.path.isabs(executable):
            return os.path.isfile(executable) and os.access(executable, os.X_OK)
        return shutil.which(executable) is not None

    def get_cli_version(self) -> Optional[str]:
        """Version string of the underlying binary, when it reports one."""
        import subprocess

        try:
            result = subprocess.run(
                [self.get_cli_executable(), "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except subprocess.SubprocessError:
            return None
        output = result.stdout.strip() or result.stderr.strip()
        return output or None

    # ==================== Model resolution ====================

    @property
    def model_path(self) -> str:
        """Resolved ggml model path (env override, else small.en default)."""
        raw = os.getenv("WHISPER_CPP_MODEL") or DEFAULT_MODEL_PATH
        return os.path.expanduser(raw)

    @property
    def models_dir(self) -> Path:
        """Directory that holds local ggml model files."""
        return Path(self.model_path).expanduser().parent

    # ==================== Prompt resolution ====================

    @property
    def prompt(self) -> Optional[str]:
        """Default initial prompt for vocabulary biasing.

        Read from ``WHISPER_CPP_PROMPT``; unset/empty means no default prompt.
        An explicit ``--prompt`` flag on ``transcripts create`` overrides this.
        """
        return os.getenv("WHISPER_CPP_PROMPT") or None

    # ==================== Settings ====================

    def save_setting(self, key: str, value: str):
        """Save a setting to the owning .env file and update environment."""
        self._set(key.upper(), value)

    def clear_settings(self):
        """Clear wrapper settings from the .env files and environment."""
        for field in self.ROOT_CONFIG_FIELDS:
            self._clear(field)


_config: Optional[Config] = None


def get_config(profile=None) -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None:
        _config = Config(profile=profile)
    return _config
