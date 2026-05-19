"""Configuration management for AtaBlog CLI wrapper."""
import subprocess
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for AtaBlog CLI wrapper.

    This is a wrapper CLI that delegates auth to wordpress and notion CLIs.
    Uses CUSTOM credential type with no local credentials stored.
    """

    DIST_NAME = "ata-blog-cli"

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

    @property
    def cli_command(self) -> str:
        """Get the underlying CLI command name."""
        return self._get("CLI_COMMAND") or "wordpress"

    @property
    def notion_database_id(self) -> str:
        """Get the Notion database ID for articles."""
        return self._get("NOTION_DATABASE_ID") or "2a317112-d9c8-42ee-a4d4-a2b8a5a20818"

    @property
    def default_author(self) -> str:
        """Get the default author for posts."""
        return self._get("DEFAULT_AUTHOR") or "Adam Bertram"

    @property
    def default_status(self) -> str:
        """Get the default status for posts."""
        return self._get("DEFAULT_STATUS") or "draft"

    def is_wordpress_available(self) -> bool:
        """Check if wordpress CLI is available."""
        import shutil
        return shutil.which("wordpress") is not None

    def is_notion_available(self) -> bool:
        """Check if notion CLI is available."""
        import shutil
        return shutil.which("notion") is not None

    def has_credentials(self) -> bool:
        """Check if underlying CLIs are authenticated."""
        try:
            wp = subprocess.run(
                ["wordpress", "auth", "status"],
                capture_output=True, text=True, timeout=10,
            )
            notion = subprocess.run(
                ["notion", "auth", "status"],
                capture_output=True, text=True, timeout=10,
            )
            return wp.returncode == 0 and notion.returncode == 0
        except Exception:
            return False

    def test_connection(self) -> dict:
        """Test connectivity to underlying CLIs."""
        results = {}

        try:
            wp = subprocess.run(
                ["wordpress", "auth", "status"],
                capture_output=True, text=True, timeout=10,
            )
            results["wordpress_auth"] = (
                "passed" if wp.returncode == 0
                else f"failed: {wp.stderr.strip()}"
            )
        except Exception as e:
            results["wordpress_auth"] = f"failed: {e}"

        try:
            notion = subprocess.run(
                ["notion", "auth", "status"],
                capture_output=True, text=True, timeout=10,
            )
            results["notion_auth"] = (
                "passed" if notion.returncode == 0
                else f"failed: {notion.stderr.strip()}"
            )
        except Exception as e:
            results["notion_auth"] = f"failed: {e}"

        wp_ok = results.get("wordpress_auth") == "passed"
        notion_ok = results.get("notion_auth") == "passed"
        results["api_test"] = (
            "passed" if (wp_ok and notion_ok)
            else "failed: one or more CLIs not authenticated"
        )

        return results


_config: Optional[Config] = None


def get_config(profile=None) -> Config:
    """Get or create config instance."""
    global _config
    if _config is None or profile is not None:
        _config = Config(profile=profile)
    return _config
