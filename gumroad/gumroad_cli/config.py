"""Gumroad personal-access-token configuration."""
from cli_tools_shared.config import BaseConfig, config_for, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


API_URL = "https://api.gumroad.com/v2"


class Config(BaseConfig):
    DIST_NAME = "gumroad-cli"
    CREDENTIAL_TYPES = [CredentialType.PERSONAL_ACCESS_TOKEN]
    DEFAULT_BASE_URL = API_URL
    AUTH_SETUP_INSTRUCTIONS = (
        "Generate an own-account access token with edit_products at "
        "https://gumroad.com/settings/advanced. Enter the access token, not an app secret."
    )

    def __init__(self, profile=None):
        super().__init__(tool_dir=resolve_tool_dir(self.DIST_NAME), profile=profile)

    def test_connection(self):
        from .client import GumroadClient
        from cli_tools_shared.exceptions import ClientError
        try:
            data = GumroadClient(config=self).call("GET", "/products")
            if not isinstance(data.get("products"), list):
                return {"api_test": "failed: Invalid Gumroad product response"}
            return {"api_test": "passed"}
        except ClientError as exc:
            return {"api_test": f"failed: {exc}"}



_configs = {}

def get_config(profile=None):
    return config_for(Config, profile, _configs)
