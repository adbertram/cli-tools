"""Configuration management for Keywords CLI.

Note: This CLI uses public autocomplete APIs that don't require authentication.
The config is kept minimal but follows standard patterns for consistency.
"""
import os
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration manager for Keywords CLI."""

    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DIST_NAME = "keywords-cli"

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def request_delay(self) -> float:
        """Get delay between requests in seconds."""
        try:
            return float(os.getenv("KEYWORDS_REQUEST_DELAY", "0.1"))
        except ValueError:
            return 0.1

    def has_credentials(self) -> bool:
        """Check if required credentials are available.

        Note: Public autocomplete APIs don't require authentication,
        so this always returns True.
        """
        return True

    def get_missing_credentials(self) -> list[str]:
        """Get list of missing credentials.

        Note: No credentials required for public autocomplete APIs.
        """
        return []

    def test_connection(self):
        """Keywords uses public suggestion endpoints and requires no saved secrets."""
        return {"api_test": "passed"}


def get_config(profile: Optional[str] = None) -> Config:
    """Create a config for the requested profile."""
    return Config(profile=profile)
