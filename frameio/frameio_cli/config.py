"""Configuration management for Frame.io CLI."""

from cli_tools_shared.config import BaseConfig, config_for, resolve_tool_dir


class Config(BaseConfig):
    DIST_NAME = "frameio-cli"
    CREDENTIAL_TYPES = []
    DEFAULT_BASE_URL = "https://api.frame.io"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )


_configs = {}


def get_config(profile=None):
    return config_for(Config, profile, _configs)
