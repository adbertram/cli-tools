"""Configuration management for TraineeDigital CLI (browser automation).

Uses BaseConfig from cli_tools_shared for profile-aware env loading.
Browser automation lives in browser.py.

``ACCOUNT_EMAIL`` is the address trainee.digital's Clerk sign-in mails the
6-digit verification code to. It is configuration, not a credential --
trainee.digital has no password, API key or token to store for this account
(it signs in through Clerk with an emailed code), so nothing here belongs in
the CLI-tools secret manager. It lives in the tool's non-auth config file at
``~/.local/share/cli-tools/trainee-digital/.env``.
"""

from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ClientError


class Config(BaseConfig):
    """Configuration for TraineeDigital — extends BaseConfig for shared auth/profile support."""

    DIST_NAME = "trainee-digital-cli"

    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://trainee.digital"
    AUTH_CONFIG_PROMPTS = [
        ("ACCOUNT_EMAIL", "trainee.digital account email (receives the login code)", False),
    ]

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def headless(self) -> bool:
        val = self._get("HEADLESS")
        return val is None or val.lower() == "true"

    @property
    def account_email(self) -> str:
        """Address trainee.digital's Clerk sign-in mails the login code to."""
        value = self._get("ACCOUNT_EMAIL")
        if not value:
            raise ClientError(
                "ACCOUNT_EMAIL is not set. trainee.digital signs in by emailing "
                "a verification code, so the CLI needs the account address. Set "
                "it with: "
                f"echo 'ACCOUNT_EMAIL=you@example.com' >> {self.config_env_file_path}"
            )
        return value

    def get_browser(self):
        """Return the BrowserAutomation subclass for this CLI."""
        from .browser import TraineeDigitalBrowser
        return TraineeDigitalBrowser(self)

    def test_connection(self) -> dict:
        """Live round-trip used by `auth test` and the auth-status API seam.

        Mints a fresh Clerk session token inside the authenticated page and
        calls the account's own profile endpoint -- the same round trip the
        worker commands depend on, so a broken token path fails here rather
        than in `tasks list`.
        """
        from .client import get_client

        client = get_client(profile=self.profile)
        try:
            profile = client.fetch_profile()
        finally:
            client.close()
        if not isinstance(profile, dict):
            raise ClientError(
                f"/api/me/profile returned {type(profile).__name__}, expected an object."
            )
        return {
            "api_test": "passed",
            "role": profile.get("role"),
            "account_email": self.account_email,
        }


# Singleton pattern for config (per profile)
_configs: dict = {}


def get_config(profile=None) -> Config:
    """Get or create config instance for a profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
