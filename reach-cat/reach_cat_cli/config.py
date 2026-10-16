"""Shared non-secret configuration for the public-only CLI."""
from cli_tools_shared.config import BaseConfig, config_for, resolve_tool_dir


class Config(BaseConfig):
    DIST_NAME = 'reach-cat-cli'
    CREDENTIAL_TYPES = []
    DEFAULT_BASE_URL = 'https://reachcat-api-default-rtdb.europe-west1.firebasedatabase.app'

    def __init__(self, profile=None):
        super().__init__(tool_dir=resolve_tool_dir(self.DIST_NAME), profile=profile)


_configs = {}


def get_config(profile=None):
    return config_for(Config, profile, _configs)
