"""Resolve the official Meta executable in this wrapper's isolated environment."""

from pathlib import Path
import sys

class Config:
    """Wrapper owns only executable selection, never upstream credentials."""

    CREDENTIAL_TYPES = []
    CLI_COMMAND = "meta"


def get_cli_executable() -> Path:
    """Use the dependency-provisioned executable, never an unrelated PATH binary."""
    return Path(sys.executable).parent / Config.CLI_COMMAND
