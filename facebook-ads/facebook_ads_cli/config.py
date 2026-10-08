"""Shared profile configuration and Meta token validation."""

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ClientError

from .catalog import API_VERSION


class Config(BaseConfig):
    DIST_NAME = "facebook-ads-cli"
    CREDENTIAL_TYPES = [CredentialType.PERSONAL_ACCESS_TOKEN]
    ADDITIONAL_AUTH_FIELDS = ("APP_SECRET",)
    ADDITIONAL_SENSITIVE_AUTH_FIELDS = ("APP_SECRET",)
    OPTIONAL_SECRET_FIELDS = ("APP_SECRET",)
    ROOT_CONFIG_FIELDS = ("API_VERSION", "HTTP_TIMEOUT", "MAX_RETRIES", "BASE_DELAY", "MAX_DELAY", "RETRY_JITTER")
    DEFAULT_BASE_URL = "https://graph.facebook.com"
    AUTH_SETUP_INSTRUCTIONS = (
        "Create a Meta app with the Marketing API product and a user/system-user access token. "
        "Use ads_read for reporting, ads_management for advertising changes, and asset access "
        "to the intended ad account. https://developers.facebook.com/docs/marketing-api/"
    )

    def __init__(self, profile=None):
        super().__init__(tool_dir=resolve_tool_dir(self.DIST_NAME), profile=profile)

    @property
    def api_version(self):
        return self._get("API_VERSION") or API_VERSION

    def test_connection(self) -> dict:
        from .client import FacebookAdsClient
        try:
            FacebookAdsClient(config=self).graph("GET", "me", {"fields": "id"})
            return {"api_test": "passed"}
        except ClientError as exc:
            return {"api_test": f"failed: {exc}"}


_configs = {}


def get_config(profile=None) -> Config:
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
