"""Configuration management for Rakuten Advertising CLI.

Rakuten Advertising's Publisher API uses OAuth 2.0 with the
``password`` grant type, where:

  Authorization: Basic base64(client_id:client_secret)
  body: grant_type=password
        scope=<publisher SID>
        username=<dashboard username>
        password=<dashboard password>

The token endpoint lives at ``https://api.linksynergy.com/token`` and
returns an access token valid for 60 minutes. Subsequent calls are made
to ``https://api.linksynergy.com/...`` with ``Authorization: Bearer
<token>``.

Required credentials (stored as a CUSTOM credential set so we can hold
both the API-app pair and the publisher SID/dashboard credentials):

  RAKUTEN_CLIENT_ID
  RAKUTEN_CLIENT_SECRET
  RAKUTEN_SID                (publisher Site/Scope ID)
  RAKUTEN_USERNAME           (publisher dashboard username)
  RAKUTEN_PASSWORD           (publisher dashboard password)

Create the API application at https://developers.rakutenadvertising.com/
(Developer Portal -> Add Application). The SID is visible in the upper
right of the publisher dashboard at https://pubdashboard.rakutenadvertising.com.
"""
import base64
import time
from typing import Optional

import requests

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


TOKEN_PATH = "/token"


class Config(BaseConfig):
    DIST_NAME = "rakuten-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS = [
        "RAKUTEN_CLIENT_ID",
        "RAKUTEN_CLIENT_SECRET",
        "RAKUTEN_SID",
        "RAKUTEN_USERNAME",
        "RAKUTEN_PASSWORD",
    ]
    CUSTOM_ALL_FIELDS = [
        "RAKUTEN_CLIENT_ID",
        "RAKUTEN_CLIENT_SECRET",
        "RAKUTEN_SID",
        "RAKUTEN_USERNAME",
        "RAKUTEN_PASSWORD",
        "BASE_URL",
    ]
    CUSTOM_LOGIN_PROMPTS = [
        ("RAKUTEN_CLIENT_ID", "Rakuten Developer Portal Client ID", False),
        ("RAKUTEN_CLIENT_SECRET", "Rakuten Developer Portal Client Secret", True),
        ("RAKUTEN_SID", "Rakuten publisher SID (site/scope id)", False),
        ("RAKUTEN_USERNAME", "Rakuten publisher dashboard username", False),
        ("RAKUTEN_PASSWORD", "Rakuten publisher dashboard password", True),
    ]
    CUSTOM_SENSITIVE_FIELDS = ["RAKUTEN_CLIENT_SECRET", "RAKUTEN_PASSWORD"]
    DEFAULT_BASE_URL = "https://api.linksynergy.com"
    LOGIN_INSTRUCTIONS = (
        "Rakuten Advertising requires five values:\n"
        "1. Create an Application at\n"
        "   https://developers.rakutenadvertising.com/\n"
        "   to obtain Client ID + Client Secret.\n"
        "2. Find your publisher SID in the top-right of\n"
        "   https://pubdashboard.rakutenadvertising.com.\n"
        "3. Provide your Rakuten publisher dashboard username + password\n"
        "   (used by the OAuth password grant, not stored on the server)."
    )

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )
        self._ensure_repo_default_env_stub()

    def _ensure_repo_default_env_stub(self) -> None:
        repo_env = self.tool_dir / ".env"
        if not repo_env.exists():
            repo_env.write_text("IS_DEFAULT_PROFILE=1\n")

    @property
    def rakuten_client_id(self) -> str:
        value = self._get("RAKUTEN_CLIENT_ID")
        if not value:
            raise ValueError("RAKUTEN_CLIENT_ID is not configured. Run 'rakuten auth login'.")
        return value

    @property
    def rakuten_client_secret(self) -> str:
        value = self._get("RAKUTEN_CLIENT_SECRET")
        if not value:
            raise ValueError("RAKUTEN_CLIENT_SECRET is not configured. Run 'rakuten auth login'.")
        return value

    @property
    def rakuten_sid(self) -> str:
        value = self._get("RAKUTEN_SID")
        if not value:
            raise ValueError("RAKUTEN_SID is not configured. Run 'rakuten auth login'.")
        return value

    @property
    def rakuten_username(self) -> str:
        value = self._get("RAKUTEN_USERNAME")
        if not value:
            raise ValueError("RAKUTEN_USERNAME is not configured. Run 'rakuten auth login'.")
        return value

    @property
    def rakuten_password(self) -> str:
        value = self._get("RAKUTEN_PASSWORD")
        if not value:
            raise ValueError("RAKUTEN_PASSWORD is not configured. Run 'rakuten auth login'.")
        return value

    def get_access_token(self, force_refresh: bool = False) -> str:
        """Return a valid OAuth access token, refreshing when expired.

        The OAuth password-grant response gives us an access token + an
        expiry in seconds. We cache both in the profile env so subsequent
        commands reuse the token until it expires.
        """
        cached = self._get("ACCESS_TOKEN")
        expires_at = self._get("TOKEN_EXPIRES_AT")
        if not force_refresh and cached and expires_at:
            try:
                if float(expires_at) - 60 > time.time():
                    return cached
            except (TypeError, ValueError):
                pass

        basic = base64.b64encode(
            f"{self.rakuten_client_id}:{self.rakuten_client_secret}".encode("utf-8")
        ).decode("ascii")
        response = requests.post(
            f"{self.base_url.rstrip('/')}{TOKEN_PATH}",
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            data={
                "grant_type": "password",
                "scope": self.rakuten_sid,
                "username": self.rakuten_username,
                "password": self.rakuten_password,
            },
            timeout=30,
        )
        if not response.ok:
            raise ValueError(
                f"Rakuten token request failed: HTTP {response.status_code}: {response.text[:500]}"
            )
        body = response.json()
        access_token = body.get("access_token")
        expires_in = body.get("expires_in")
        if not access_token:
            raise ValueError(f"Rakuten token response missing access_token: {body}")
        self._set("ACCESS_TOKEN", access_token)
        if expires_in:
            self._set("TOKEN_EXPIRES_AT", str(time.time() + float(expires_in)))
        return access_token

    def test_connection(self) -> dict:
        if not self.has_credentials():
            missing = ", ".join(self.get_missing_credentials())
            return {"api_test": f"failed: missing {missing}"}
        try:
            token = self.get_access_token(force_refresh=True)
        except Exception as exc:
            return {"api_test": f"failed: {exc}"}
        # Smallest valid call: the advertisers API
        response = requests.get(
            f"{self.base_url.rstrip('/')}/advertisersearch/1.0",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params={"status": "approved"},
            timeout=30,
        )
        if response.ok:
            return {"api_test": "passed"}
        return {"api_test": f"failed: HTTP {response.status_code}: {response.text[:500]}"}


_configs: dict = {}


def get_config(profile: Optional[str] = None) -> Config:
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
