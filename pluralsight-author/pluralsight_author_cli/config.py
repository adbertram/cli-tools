from functools import cache

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://app.pluralsight.com/author-home/opportunities/all"
    DIST_NAME = "pluralsight-author-cli"

    def __init__(self, profile=None):
        super().__init__(tool_dir=resolve_tool_dir(self.DIST_NAME), profile=profile)

    def get_browser(self):
        from .browser import PluralsightAuthorBrowser

        return PluralsightAuthorBrowser(self)

    def test_connection(self) -> dict:
        if not self.get_browser().is_authenticated():
            raise RuntimeError("Saved browser session is not authenticated.")
        return {"api_test": "passed"}

    @property
    def storage_dir(self):
        return self.get_profile_data_dir()


@cache
def get_config(profile=None) -> Config:
    return Config(profile=profile)
