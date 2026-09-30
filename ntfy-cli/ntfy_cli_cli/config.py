"""Non-secret wrapper configuration."""

import shutil
from typing import Optional
from cli_tools_shared.config import BaseConfig, resolve_tool_dir


class Config(BaseConfig):
    DIST_NAME = "ntfy-cli"
    CREDENTIAL_TYPES = []
    ROOT_CONFIG_FIELDS = ("CLI_COMMAND", "CLI_PATH")

    def __init__(self, profile: Optional[str] = None):
        super().__init__(tool_dir=resolve_tool_dir(self.DIST_NAME), profile=profile)

    @property
    def cli_command(self) -> str:
        return self._get("CLI_COMMAND") or "ntfy"

    def get_cli_executable(self) -> str:
        return self._get("CLI_PATH") or self.cli_command

    def is_cli_available(self) -> bool:
        return shutil.which(self.get_cli_executable()) is not None


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config
