"""Configuration management for FreshBooks CLI."""
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):

    DIST_NAME = "freshbooks-cli"
    CREDENTIAL_TYPES = [CredentialType.OAUTH]
    DEFAULT_BASE_URL = "https://api.freshbooks.com"
    OAUTH_AUTH_URL = "https://my.freshbooks.com/service/auth/oauth/authorize"
    OAUTH_TOKEN_URL = "https://api.freshbooks.com/auth/oauth/token"
    OAUTH_REDIRECT_URI = "https://localhost/callback"
    AUTH_EXTRA_PROMPTS = [("ACCOUNT_ID", "FreshBooks account ID", False)]

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def account_id(self) -> Optional[str]:
        return self._get("ACCOUNT_ID")

    @property
    def redirect_uri(self) -> Optional[str]:
        return self._get("REDIRECT_URI")

    @property
    def default_terms(self) -> Optional[str]:
        terms = self._get("DEFAULT_TERMS")
        if terms:
            terms = terms.replace("\\n", "\n")
        return terms

    def has_credentials(self) -> bool:
        return bool(self.account_id and self.client_id and self.client_secret and self.access_token)

    def get_missing_credentials(self) -> list:
        missing = []
        if not self.account_id:
            missing.append("ACCOUNT_ID")
        if not self.client_id:
            missing.append("CLIENT_ID")
        if not self.client_secret:
            missing.append("CLIENT_SECRET")
        if not self.access_token:
            missing.append("ACCESS_TOKEN")
        return missing

    def test_connection(self) -> dict:
        import requests

        response = requests.get(
            f"{self.base_url}/accounting/account/{self.account_id}/users/clients",
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
            },
            params={"per_page": 1},
            timeout=10,
        )
        response.raise_for_status()
        return {"api_test": "passed", "account_id": self.account_id}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
