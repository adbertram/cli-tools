"""Configuration management for Tiktok CLI."""
import os
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir


class Config(BaseConfig):
    """Configuration manager for Tiktok CLI."""

    CREDENTIAL_TYPES: list = []  # custom field set; managed by this subclass
    DIST_NAME = "tiktok-cli"

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def base_url(self) -> str:
        """Get TikTok base URL."""
        return os.getenv("TIKTOK_BASE_URL", "https://www.tiktok.com")


# Global config instance - singleton pattern
_config: Optional[Config] = None


def get_config() -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config
