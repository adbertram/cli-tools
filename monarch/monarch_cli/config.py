"""Configuration management for Monarch CLI."""
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for Monarch Money CLI.

    Uses USERNAME_PASSWORD credential type with an extra MFA_SECRET field.
    The session pickle is stored in the profile data directory.
    """

    DIST_NAME = "monarch-cli"

    CREDENTIAL_TYPES = [CredentialType.USERNAME_PASSWORD]
    DEFAULT_BASE_URL = "https://api.monarch.com"

    # MFA_SECRET is handled by the login handler (not AUTH_EXTRA_PROMPTS)
    # because it's optional — cli-tools-shared rejects empty extra prompts.

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def email(self) -> Optional[str]:
        """Get email (alias for username)."""
        return self.username

    @property
    def mfa_secret(self) -> Optional[str]:
        """Get MFA secret key for TOTP generation."""
        return self._get("MFA_SECRET")

    @property
    def session_file(self) -> Path:
        """Get path to session pickle file in profile data directory."""
        return self.get_profile_data_dir() / "mm_session.pickle"

    def has_session(self) -> bool:
        """Check if a saved session exists."""
        return self.session_file.exists()

    def clear_session(self):
        """Delete the session file."""
        if self.session_file.exists():
            self.session_file.unlink()

    def test_connection(self) -> Optional[dict]:
        """Test API connectivity by fetching subscription details."""
        from .client import MonarchClient
        try:
            client = MonarchClient(config=self)
            sub = client.get_subscription_details()
            status = sub.get("subscription", {}).get("status", "unknown")
            return {"api_test": "passed", "subscription_status": status}
        except Exception as e:
            return {"api_test": f"failed: {e}"}


# Global config factory
_configs = {}


def get_config(profile=None) -> Config:
    """Get or create a Config instance for the given profile."""
    key = profile or "__default__"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
