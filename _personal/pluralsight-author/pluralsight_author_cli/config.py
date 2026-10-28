from functools import cache

from cli_tools_shared.config import (
    BaseConfig,
    _read_env_values,
    _write_env_values,
    list_env_files,
    profile_name_from_path,
    resolve_tool_dir,
)
from cli_tools_shared.credentials import CredentialType

AUTH_METHOD_OPPORTUNITIES = "opportunities"
AUTH_METHOD_AUTHOR_KIT = "author_kit"


def _ensure_profile_auth_methods(tool_name: str) -> None:
    for env_path in list_env_files(tool_name):
        if profile_name_from_path(env_path) != "default":
            continue
        values = _read_env_values(env_path)
        if values.get("AUTH_METHOD", "").strip():
            continue
        values["AUTH_METHOD"] = AUTH_METHOD_OPPORTUNITIES
        _write_env_values(env_path, values)


class Config(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://app.pluralsight.com/author-home/opportunities/all"
    DIST_NAME = "pluralsight-author-cli"
    PROFILE_AUTH_TYPE_FIELD = "AUTH_METHOD"
    PROFILE_AUTH_TYPES = {
        AUTH_METHOD_OPPORTUNITIES: [],
        AUTH_METHOD_AUTHOR_KIT: [],
    }
    ADDITIONAL_AUTH_FIELDS = ("AUTH_METHOD",)

    def __init__(self, profile=None, profile_auth_type=None):
        tool_dir = resolve_tool_dir(self.DIST_NAME)
        _ensure_profile_auth_methods(tool_dir.name)
        super().__init__(
            tool_dir=tool_dir,
            profile=profile,
            profile_auth_type=profile_auth_type,
        )

    def _active_auth_method(self) -> str:
        return self._profile_auth_type_for_env(self.env_file_path)

    def get_browser(self):
        from .browser import PluralsightAuthorBrowser, PluralsightAuthorKitBrowser

        if self._active_auth_method() == AUTH_METHOD_AUTHOR_KIT:
            return PluralsightAuthorKitBrowser(self)
        return PluralsightAuthorBrowser(self)

    def test_connection(self) -> dict:
        if not self.get_browser().is_authenticated():
            raise RuntimeError("Saved browser session is not authenticated.")
        return {"api_test": "passed"}


@cache
def get_config(profile=None, profile_auth_type=None) -> Config:
    return Config(profile=profile, profile_auth_type=profile_auth_type)
