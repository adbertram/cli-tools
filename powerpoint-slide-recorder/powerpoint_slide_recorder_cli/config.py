"""Configuration management for PowerPoint Slide Recorder CLI."""

from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir, config_for


class Config(BaseConfig):
    """Configuration for local profile storage."""

    CREDENTIAL_TYPES: list = []
    DIST_NAME = "powerpoint-slide-recorder-cli"

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )


_configs: dict[str, Config] = {}


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create the config instance for a profile."""
    return config_for(Config, profile, _configs)
