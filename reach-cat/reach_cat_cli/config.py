"""Public discovery and saved browser identity configuration."""
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.config import BaseConfig, config_for, resolve_tool_dir


class Config(BaseConfig):
    DIST_NAME = 'reach-cat-cli'
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = 'https://reachcat-api-default-rtdb.europe-west1.firebasedatabase.app'

    def __init__(self, profile=None):
        super().__init__(tool_dir=resolve_tool_dir(self.DIST_NAME), profile=profile)

    def get_browser(self):
        from .browser import ReachCatBrowser
        return ReachCatBrowser(self)

    def test_connection(self):
        from .client import ReachCatClient
        client = ReachCatClient(config=self)
        try:
            client.account()
            return {'api_test': 'passed'}
        finally:
            client.close()


_configs = {}


def get_config(profile=None):
    return config_for(Config, profile, _configs)
