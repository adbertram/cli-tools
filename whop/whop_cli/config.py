"""Whop browser profiles and explicit Content Rewards location."""
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType

class Config(BaseConfig):
    DIST_NAME = "whop-cli"
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://whop.com"
    ROOT_CONFIG_FIELDS = ("REWARDS_URL",)
    AUTH_CONFIG_PROMPTS = [("REWARDS_URL", "Embedded Content Rewards URL (https://...apps.whop.com/c/exp_...)", False)]
    LOGIN_INSTRUCTIONS = (
        "Sign in to Whop, then open your Content Rewards experience in the same Chrome window "
        "before confirming login. Browser/MFA completion is manual; no credentials are submitted automatically. "
        "Reusable credentials belong in the CLI-tools secret manager; the CLI manages profile session state."
    )
    def __init__(self, profile=None):
        super().__init__(tool_dir=resolve_tool_dir(self.DIST_NAME), profile=profile)
    @property
    def rewards_url(self):
        return self._get("REWARDS_URL")
    def get_browser(self):
        from .browser import WhopBrowser
        return WhopBrowser(self)
    def test_connection(self):
        from .client import WhopClient
        client = WhopClient(self)
        try:
            client.account()
            return {"api_test": "passed"}
        finally:
            client.close()

def get_config(profile=None):
    return Config(profile=profile)
