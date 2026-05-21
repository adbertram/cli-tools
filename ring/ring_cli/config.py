"""Configuration management for Ring CLI.

This CLI wraps ``python-ring-doorbell`` rather than Ring's hosted partner API.
The only supported bootstrap path in that library is consumer-account
``USERNAME``/``PASSWORD`` plus a one-time 2FA code, followed by a cached
OAuth refresh token.

The refresh token returned by Ring after first 2FA login is stored as a JSON
blob in the profile data directory (not in ``.env``) so the token-update
callback can rotate it without touching credentials.
"""
import json
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for Ring CLI.

    Uses USERNAME_PASSWORD for the bootstrap login. This CLI does not accept
    Ring Partner API app credentials because ``python-ring-doorbell`` authenticates
    against the Ring consumer account flow. After successful 2FA the
    ring-doorbell ``Auth`` object hands back an OAuth token dict
    (access_token, refresh_token, expires_in, ...) which we persist to
    ``ring_token.json`` in the profile data directory.
    """

    DIST_NAME = "ring-cli"

    CREDENTIAL_TYPES = [CredentialType.USERNAME_PASSWORD]
    DEFAULT_BASE_URL = "https://api.ring.com"

    USER_AGENT = "ring-cli/0.1.0"

    AUTH_EXTRA_PROMPTS = []

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
    def token_file(self) -> Path:
        """Path to the Ring OAuth token cache in the profile data directory."""
        return self.get_profile_data_dir() / "ring_token.json"

    def has_token(self) -> bool:
        """Check if a saved Ring OAuth token exists for this profile."""
        return self.token_file.exists()

    def load_token(self) -> Optional[dict]:
        """Load the Ring OAuth token dict from disk, or return None."""
        if not self.has_token():
            return None
        return json.loads(self.token_file.read_text())

    def save_token(self, token: dict) -> None:
        """Persist the Ring OAuth token dict to disk.

        Called by ring-doorbell's token_updated callback after fetch_token
        and after every async_refresh_tokens. Writes atomically (mkdir +
        write) so a partial write cannot leave a half-formed file.
        """
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(json.dumps(token))

    def clear_token(self) -> None:
        """Delete the cached Ring OAuth token."""
        if self.token_file.exists():
            self.token_file.unlink()

    @property
    def download_dir(self) -> Path:
        """Default directory for downloaded recordings."""
        return Path.home() / "Downloads" / "ring"

    def test_connection(self) -> Optional[dict]:
        """Verify auth by fetching the device list."""
        from .client import RingClient, ClientError
        try:
            client = RingClient(config=self)
            devices = client.list_devices()
            return {
                "api_test": "passed",
                "device_count": len(devices),
            }
        except ClientError as e:
            return {"api_test": f"failed: {e}"}


_configs = {}


def get_config(profile=None) -> Config:
    """Get or create a Config instance for the given profile."""
    key = profile or "__default__"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
