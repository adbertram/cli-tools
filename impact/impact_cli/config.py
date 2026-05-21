"""Configuration management for Impact CLI."""
import requests

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    DIST_NAME = "impact-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS = ["IMPACT_ACCOUNT_SID", "IMPACT_AUTH_TOKEN"]
    CUSTOM_ALL_FIELDS = ["IMPACT_ACCOUNT_SID", "IMPACT_AUTH_TOKEN"]
    CUSTOM_LOGIN_PROMPTS = [
        ("IMPACT_ACCOUNT_SID", "Impact Account SID", False),
        ("IMPACT_AUTH_TOKEN", "Impact Auth Token", True),
    ]
    CUSTOM_SENSITIVE_FIELDS = ["IMPACT_AUTH_TOKEN"]
    DEFAULT_BASE_URL = "https://api.impact.com"

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def impact_account_sid(self) -> str:
        value = self._get("IMPACT_ACCOUNT_SID")
        if value is None:
            raise ValueError("IMPACT_ACCOUNT_SID is not configured")
        return value

    @property
    def impact_auth_token(self) -> str:
        value = self._get("IMPACT_AUTH_TOKEN")
        if value is None:
            raise ValueError("IMPACT_AUTH_TOKEN is not configured")
        return value

    def test_connection(self):
        """Validate the saved Impact credentials."""
        if not self.has_credentials():
            missing = ", ".join(self.get_missing_credentials())
            return {"api_test": f"failed: missing {missing}"}

        response = requests.get(
            f"{self.base_url.rstrip('/')}/Mediapartners/{self.impact_account_sid}/CompanyInformation",
            headers={"Accept": "application/json"},
            auth=(self.impact_account_sid, self.impact_auth_token),
            timeout=30,
        )
        if response.ok:
            return {"api_test": "passed"}

        return {"api_test": f"failed: HTTP {response.status_code}: {response.text[:500]}"}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
