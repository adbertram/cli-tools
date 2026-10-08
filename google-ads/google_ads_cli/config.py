"""Profile-aware Google Ads OAuth configuration."""
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    DIST_NAME = "google-ads-cli"
    CREDENTIAL_TYPES = [CredentialType.OAUTH_AUTHORIZATION_CODE]
    DEFAULT_BASE_URL = "https://googleads.googleapis.com"
    OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
    OAUTH_SCOPES = ["https://www.googleapis.com/auth/adwords"]
    OAUTH_TOKEN_AUTH = "body"
    OAUTH_PKCE = True
    OAUTH_STATE = True
    OAUTH_REDIRECT_URI = "http://localhost"
    OAUTH_EXTRA_AUTH_PARAMS = {"access_type": "offline", "prompt": "consent"}
    ROOT_CONFIG_FIELDS = ["LOGIN_CUSTOMER_ID", "LINKED_CUSTOMER_ID", "CUSTOMER_ID"]
    AUTH_SETUP_INSTRUCTIONS = (
        "Enable Google Ads API and obtain API access for your Google Cloud project. "
        "Create an OAuth client with a permitted redirect URI. Client ID and secret "
        "are saved through the CLI-tools secret manager by auth login. "
        "Ads permission and adwords scope are required. Developer tokens were sunset "
        "September 9, 2026 and are not required."
    )

    def __init__(self, profile=None):
        super().__init__(tool_dir=resolve_tool_dir(self.DIST_NAME), profile=profile)

    def test_connection(self):
        from .client import GoogleAdsClient
        from cli_tools_shared.exceptions import ClientError, CredentialError
        try:
            result = GoogleAdsClient(config=self).call("CustomerService", "list_accessible_customers", {})
            return {"api_test": "passed", "accessible_customer_count": len(result.get("resource_names", []))}
        except (ClientError, CredentialError) as exc:
            return {"api_test": f"failed: {exc}"}


def get_config(profile=None):
    # Config resolves the active profile on each call; never cache across profile switches.
    return Config(profile=profile)
