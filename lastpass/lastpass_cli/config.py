"""Configuration management for Lastpass CLI wrapper."""
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for LastPass CLI wrapper.

    Uses CUSTOM credential type with only USERNAME (email).
    The underlying lpass CLI handles its own password prompt
    via pinentry — we never store or prompt for the password.
    """

    DIST_NAME = "lastpass-cli"

    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DEFAULT_BASE_URL = ""

    # Only prompt for email — lpass handles password via pinentry
    CUSTOM_LOGIN_PROMPTS = [
        ("USERNAME", "LastPass email", False),
    ]
    CUSTOM_REQUIRED_FIELDS = ["USERNAME"]
    CUSTOM_ALL_FIELDS = ["USERNAME"]

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def cli_command(self) -> str:
        """Get the underlying CLI command name (always lpass)."""
        return "lpass"

    def get_cli_executable(self) -> str:
        """Get the CLI executable path."""
        return self.cli_command

    def is_cli_available(self) -> bool:
        """Check if the underlying CLI is available in PATH."""
        return shutil.which(self.get_cli_executable()) is not None

    def get_cli_version(self) -> Optional[str]:
        """Get the version of the underlying CLI (if available)."""
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

    def test_connection(self) -> Optional[dict]:
        """Test connectivity by making an actual API call (lpass ls).

        Uses LPASS_AGENT_DISABLE=1 to read decryption key from plaintext_key
        file on disk, avoiding the buggy lpass agent that crashes on macOS.
        """
        try:
            env = {**os.environ, "LPASS_AGENT_DISABLE": "1"}
            result = subprocess.run(
                [self.get_cli_executable(), "ls"],
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
            )
            if result.returncode == 0:
                return {"api_test": "passed"}
            return {"api_test": f"failed: {result.stderr.strip() or result.stdout.strip()}"}
        except Exception as e:
            return {"api_test": f"failed: {e}"}


# Global config factory
_configs = {}


def get_config(profile=None) -> Config:
    """Get or create a Config instance for the given profile."""
    key = profile or "__default__"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
