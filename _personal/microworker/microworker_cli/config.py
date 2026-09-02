"""Configuration management for the Microworker CLI.

The site CLIs this tool runs come from the MicroWorker project's `config.json`
(see `sites.py`), not from this profile. The profile carries no credentials.
"""

from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir


class Config(BaseConfig):
    """Configuration manager for the Microworker CLI."""

    DIST_NAME = "microworker-cli"
    CREDENTIAL_TYPES = []
    DEFAULT_BASE_URL = ""
    ROOT_CONFIG_FIELDS = ("CLI_COMMAND",)

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )


_config: Optional[Config] = None


def get_config(profile=None) -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config
