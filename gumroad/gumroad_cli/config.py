"""Gumroad owns its PAT; Notion retains its existing separately managed token."""
import requests
from cli_tools_shared.config import BaseConfig, config_for, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    DIST_NAME = "gumroad-cli"
    CREDENTIAL_TYPES = [CredentialType.PERSONAL_ACCESS_TOKEN]
    DEFAULT_BASE_URL = "https://api.gumroad.com/v2"
    AUTH_SETUP_INSTRUCTIONS = (
        "Generate an own-account access token with edit_products at "
        "https://gumroad.com/settings/advanced. Enter the access token, not an app secret. "
        "Book commands separately reuse the CLI-tools secret notion-api-token."
    )

    def __init__(self, profile=None):
        super().__init__(tool_dir=resolve_tool_dir(self.DIST_NAME), profile=profile)

    def test_connection(self):
        try:
            response = requests.get(
                self.DEFAULT_BASE_URL + "/products",
                headers={"Authorization": f"Bearer {self.personal_access_token}"},
                timeout=45, allow_redirects=False,
            )
            if response.status_code != 200:
                return {"api_test": f"failed: Gumroad HTTP {response.status_code}"}
            data = response.json()
            if not isinstance(data, dict) or data.get("success") is not True or not isinstance(data.get("products"), list):
                return {"api_test": "failed: Invalid Gumroad product response"}
            return {"api_test": "passed"}
        except (requests.RequestException, ValueError):
            return {"api_test": "failed: Gumroad connection failed"}


_configs = {}

def get_config(profile=None):
    return config_for(Config, profile, _configs)
