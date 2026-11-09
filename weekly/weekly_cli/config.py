"""Shared profile configuration for Weekly's captured native session."""
from cli_tools_shared.config import BaseConfig, config_for, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ClientError
from .constants import CLOUD_FUNCTIONS_BASE


class Config(BaseConfig):
    DIST_NAME = 'weekly-cli'
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS = ['SESSION_IMPORTED']
    CUSTOM_ALL_FIELDS = ['SESSION_IMPORTED', 'SESSION_DATA']
    CUSTOM_SENSITIVE_FIELDS = ['SESSION_DATA']
    DEFAULT_BASE_URL = CLOUD_FUNCTIONS_BASE

    def __init__(self, profile=None):
        super().__init__(tool_dir=resolve_tool_dir(self.DIST_NAME), profile=profile)

    def test_connection(self):
        from .session import refresh
        try:
            refresh(self)
            return {'api_test': 'passed'}
        except ClientError as error:
            return {'api_test': f'failed: {error}'}


_configs = {}


def get_config(profile=None):
    return config_for(Config, profile, _configs)
