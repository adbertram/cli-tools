"""Configuration management for Tiktok CLI."""
import os
import subprocess
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration manager for Tiktok CLI."""

    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS: list = []
    DIST_NAME = "tiktok-cli"
    LOGIN_INSTRUCTIONS = (
        "TikTok transcript downloads do not use CLI-managed credentials.\n"
        "  1. Install yt-dlp: brew install yt-dlp\n"
        "  2. If a video requires cookies or a logged-in browser session,\n"
        "     configure that directly in yt-dlp before using this wrapper."
    )

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def base_url(self) -> str:
        """Get TikTok base URL."""
        return os.getenv("TIKTOK_BASE_URL", "https://www.tiktok.com")

    def test_connection(self) -> Optional[dict]:
        """Verify the upstream yt-dlp dependency is available."""
        try:
            result = subprocess.run(
                ["yt-dlp", "--version"],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
        except FileNotFoundError:
            return {"api_test": "failed: yt-dlp not installed", "upstream": "yt-dlp"}
        except subprocess.CalledProcessError as exc:
            message = (exc.stderr or exc.stdout or str(exc)).strip()
            return {"api_test": f"failed: {message}", "upstream": "yt-dlp"}
        except subprocess.TimeoutExpired:
            return {"api_test": "failed: yt-dlp --version timed out", "upstream": "yt-dlp"}

        return {
            "api_test": "passed",
            "upstream": "yt-dlp",
            "version": result.stdout.strip(),
        }


# Global config instance - singleton pattern
_config: Optional[Config] = None


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None or profile is not None:
        _config = Config(profile=profile)
    return _config
