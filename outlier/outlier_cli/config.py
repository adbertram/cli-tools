"""Configuration management for Outlier CLI (browser automation).

Uses BaseConfig from cli_tools_shared for profile-aware env loading.
Browser automation lives in browser.py.

`ACCOUNT_EMAIL` is the address Outlier mails the passwordless sign-in link to.
It is configuration, not a credential — there is no Outlier password, API key
or token to store, so nothing here belongs in the CLI-tools secret manager. It
lives in the tool's non-auth config file at
`~/.local/share/cli-tools/outlier/.env`.
"""

from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ClientError


class Config(BaseConfig):
    """Configuration for Outlier — extends BaseConfig for shared auth/profile support."""

    DIST_NAME = "outlier-cli"

    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://app.outlier.ai"

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
        """Address Outlier mails the sign-in link to."""
        value = self._get("ACCOUNT_EMAIL")
        if not value:
            raise ClientError(
                "ACCOUNT_EMAIL is not set. Outlier signs in by emailing a link, "
                "so the CLI needs the account address. Set it with: "
                f"echo 'ACCOUNT_EMAIL=you@example.com' >> {self.config_env_file_path}"
            )
        return value

    def get_browser(self):
        """Return the BrowserAutomation subclass for this CLI."""
        from .browser import OutlierBrowser
        return OutlierBrowser(self)


    def test_connection(self) -> dict:
        """Live round-trip used by `auth test` / `auth status`.

        `create_auth_app` only mounts an `auth test` command when the config
        overrides this, so it is the command's implementation, not an extra.
        """
        from .client import get_client

        client = get_client(profile=self.profile)
        try:
            user = client.get_logged_in_user()
        finally:
            client.close()
        return {
            "api_test": "passed",
            "user_id": user.get("id"),
            "worker_status": user.get("workerStatus"),
        }

# Singleton pattern for config (per profile)
_configs: dict = {}


def get_config(profile=None) -> Config:
    """Get or create config instance for a profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
