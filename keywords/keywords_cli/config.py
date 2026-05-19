"""Configuration management for Keywords CLI.

Note: This CLI uses public autocomplete APIs that don't require authentication.
The config is kept minimal but follows standard patterns for consistency.
"""
import os
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir


class Config(BaseConfig):
    """Configuration manager for Keywords CLI."""

    CREDENTIAL_TYPES: list = []  # public APIs — no auth required
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


# Global config instance - singleton pattern
_config: Optional[Config] = None


def get_config() -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config
