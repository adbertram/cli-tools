"""Whop browser profiles and explicit Content Rewards location."""
from cli_tools_shared.config import BaseConfig, config_for, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ClientError
from urllib.parse import urlsplit
import re

def rewards_location(raw):
    """Validate the service-owned Content Rewards URL without loading a profile."""
    if not raw:
        raise ClientError("rewards_url_unconfigured: run whop config set-rewards-url URL")
    u = urlsplit(raw)
    if u.scheme != "https" or not re.fullmatch(r"[a-z0-9]+\.apps\.whop\.com", u.netloc) or not re.fullmatch(r"/c/exp_[A-Za-z0-9]+/?", u.path) or u.query or u.fragment or raw != raw.strip() or any(ord(c) < 32 for c in raw):
        raise ClientError("invalid_rewards_url")
    return f"https://{u.netloc}", u.path.rstrip("/")

class Config(BaseConfig):
    DIST_NAME = "whop-cli"
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://whop.com"
    PORTABLE_BROWSER_SESSION = True
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
    def browser_session_origins(self) -> tuple[str, ...]:
        origin, _ = rewards_location(self.rewards_url)
        return ("https://whop.com", origin)
    def browser_session_cookie_domains(self) -> tuple[str, ...]:
        origin, _ = rewards_location(self.rewards_url)
        return ("whop.com", urlsplit(origin).hostname)
    def browser_session_identity(self, browser) -> dict[str, str]:
        from .client import WhopClient
        row = WhopClient(config=self, browser=browser).account()
        return {"account_id": row["id"], "username": row["username"]}
    def test_connection(self):
        from .client import WhopClient
        client = WhopClient(self)
        try:
            client.account()
            return {"api_test": "passed"}
        finally:
            client.close()

_configs = {}


def get_config(profile=None):
    return config_for(Config, profile, _configs)
