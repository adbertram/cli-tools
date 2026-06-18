"""Configuration management for Airbnb CLI."""

import json
from pathlib import Path

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ClientError


class Config(BaseConfig):
    DIST_NAME = "airbnb-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS = ["AUTH_COOKIES_JSON", "AIRBNB_API_KEY"]
    CUSTOM_ALL_FIELDS = ["AUTH_COOKIES_JSON", "AIRBNB_API_KEY"]
    CUSTOM_LOGIN_PROMPTS = []
    CUSTOM_SENSITIVE_FIELDS = ["AUTH_COOKIES_JSON", "AIRBNB_API_KEY"]
    DEFAULT_BASE_URL = "https://www.airbnb.com"
    ADDITIONAL_AUTH_FIELDS = ("AUTH_COOKIES_JSON", "AIRBNB_API_KEY")
    ADDITIONAL_SENSITIVE_AUTH_FIELDS = ("AUTH_COOKIES_JSON", "AIRBNB_API_KEY")
    BROWSER_USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/137.0.0.0 Safari/537.36"
    )

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def storage_dir(self) -> Path:
        """Profile-aware storage directory for runtime state."""
        return self.get_profile_data_dir()

    @property
    def browser_user_agent(self) -> str:
        return self._get("BROWSER_USER_AGENT") or self.BROWSER_USER_AGENT

    @property
    def airbnb_api_key(self) -> str | None:
        return self._get("AIRBNB_API_KEY")

    @property
    def auth_cookies_json(self) -> str | None:
        return self._get("AUTH_COOKIES_JSON")

    @property
    def auth_cookies(self) -> list[dict]:
        raw = self.auth_cookies_json
        if not raw:
            return []
        try:
            cookies = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ClientError("Saved Airbnb Chrome cookies are not valid JSON. Run 'airbnb auth login --force'.") from exc
        if not isinstance(cookies, list):
            raise ClientError("Saved Airbnb Chrome cookies must be a JSON list. Run 'airbnb auth login --force'.")
        return cookies

    def save_chrome_session(self, cookies: list[dict], api_key: str) -> None:
        self._set("AUTH_COOKIES_JSON", json.dumps(cookies, separators=(",", ":")))
        self._set("AIRBNB_API_KEY", api_key)

    def has_saved_session(self) -> bool:
        return bool(self.auth_cookies_json and self.airbnb_api_key)

    def get_missing_credentials(self) -> list[str]:
        missing = []
        if not self.auth_cookies_json:
            missing.append("AUTH_COOKIES_JSON")
        if not self.airbnb_api_key:
            missing.append("AIRBNB_API_KEY")
        return missing

    def clear_session(self) -> None:
        self._clear("AUTH_COOKIES_JSON")
        self._clear("AIRBNB_API_KEY")

    def get_browser(self):
        from .browser import AirbnbBrowser

        return AirbnbBrowser(self)

    def test_connection(self) -> dict:
        """Validate saved credentials with a live API call."""
        from .client import AirbnbClient

        try:
            AirbnbClient(config=self, max_retries=0).verify_host_session()
            return {"api_test": "passed"}
        except ClientError as exc:
            return {"api_test": f"failed: {exc}"}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
