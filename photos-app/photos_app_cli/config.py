"""Configuration management for photos-app CLI."""
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for photos-app CLI.

    No API credentials needed - this CLI accesses the local Photos library.
    Uses CUSTOM credential type with no required fields.
    """

    DIST_NAME = "photos-app-cli"

    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS = []
    CUSTOM_ALL_FIELDS = []
    CUSTOM_LOGIN_PROMPTS = []
    CUSTOM_EPHEMERAL_FIELDS = []
    CUSTOM_SENSITIVE_FIELDS = []

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def test_connection(self) -> Optional[dict]:
        """Test Photos library accessibility."""
        from .client import PhotosClient, ClientError
        try:
            client = PhotosClient(library_path=None)
            if client.is_available():
                return {
                    "api_test": "passed",
                    "library_path": str(client.library_path),
                    "photo_count": client.get_photo_count(),
                }
            return {"api_test": "failed: Photos library not accessible"}
        except ClientError as e:
            return {"api_test": f"failed: {e}"}


# Singleton pattern for config
_configs = {}


def get_config(profile=None) -> Config:
    """Get or create config instance for a profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
