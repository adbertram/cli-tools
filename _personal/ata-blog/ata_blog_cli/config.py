"""Configuration management for AtaBlog CLI wrapper."""
import json
import subprocess
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


def _active_profile_status(cli_command: str) -> dict:
    """Return the active profile status payload for a delegated CLI."""
    result = subprocess.run(
        [cli_command, "auth", "status"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())

    payload = json.loads(result.stdout)
    profiles = payload.get("profiles")
    if not isinstance(profiles, list):
        raise RuntimeError(f"{cli_command} auth status returned invalid profiles payload")

    active_profiles = [profile for profile in profiles if profile.get("active") is True]
    if len(active_profiles) != 1:
        raise RuntimeError(f"{cli_command} auth status did not return exactly one active profile")

    profile = active_profiles[0]
    credential_types = profile.get("credential_types")
    if not isinstance(credential_types, dict) or not credential_types:
        raise RuntimeError(f"{cli_command} auth status returned no credential_types details")

    return profile


def _active_profile_has_credentials(cli_command: str) -> bool:
    """Return whether the delegated CLI has saved credentials in its active profile."""
    credential_types = _active_profile_status(cli_command)["credential_types"]
    return any(
        isinstance(details, dict) and details.get("credentials_saved") is True
        for details in credential_types.values()
    )


def _active_profile_auth_status(cli_command: str) -> tuple[bool, str]:
    """Return whether the active profile for a delegated CLI is authenticated."""
    profile = _active_profile_status(cli_command)
    if profile.get("authenticated") is True:
        return True, "passed"

    credential_types = profile["credential_types"]
    messages = []
    for credential_type, details in credential_types.items():
        if not isinstance(details, dict):
            raise RuntimeError(
                f"{cli_command} auth status returned invalid credential details for {credential_type}"
            )
        message = details.get("message") or details.get("api_test") or "not authenticated"
        messages.append(f"{credential_type}: {message}")

    return False, "; ".join(messages)


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
    ROOT_CONFIG_FIELDS = (
        "NOTION_DATABASE_ID",
        "DEFAULT_AUTHOR",
        "DEFAULT_STATUS",
        "ATABLOGGER_SPONSORS_FILE",
        "WPENGINE_SSH_HOST",
        "WPENGINE_SSH_USER",
        "WPENGINE_SSH_IDENTITY_FILE",
        "WPENGINE_SITE_PATH",
    )

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

    def _require(self, key: str) -> str:
        """Return a required non-secret config value or explain how to set it."""
        value = self._get(key)
        if not value:
            raise ValueError(
                f"{key} is not set. Add it to ~/.local/share/cli-tools/ata-blog/.env"
            )
        return value

    @property
    def sponsors_file(self) -> str:
        """Get the path to the sponsor registry (sponsors.json)."""
        return self._require("ATABLOGGER_SPONSORS_FILE")

    @property
    def wpengine_ssh_host(self) -> str:
        """Get the WP Engine SSH host."""
        return self._require("WPENGINE_SSH_HOST")

    @property
    def wpengine_ssh_user(self) -> str:
        """Get the WP Engine SSH user."""
        return self._require("WPENGINE_SSH_USER")

    @property
    def wpengine_ssh_identity_file(self) -> str:
        """Get the SSH identity file registered with WP Engine."""
        return self._require("WPENGINE_SSH_IDENTITY_FILE")

    @property
    def wpengine_site_path(self) -> str:
        """Get the WP Engine site root that holds the WordPress install."""
        return self._require("WPENGINE_SITE_PATH")

    def is_wordpress_available(self) -> bool:
        """Check if wordpress CLI is available."""
        import shutil
        return shutil.which("wordpress") is not None

    def is_notion_available(self) -> bool:
        """Check if notion CLI is available."""
        import shutil
        return shutil.which("notion") is not None

    def has_credentials(self) -> bool:
        """Check if delegated CLIs have saved credentials in their active profiles."""
        try:
            return (
                _active_profile_has_credentials("wordpress")
                and _active_profile_has_credentials("notion")
            )
        except Exception:
            return False

    def test_connection(self) -> dict:
        """Test connectivity to underlying CLIs."""
        results = {}

        try:
            wp_ok, wp_message = _active_profile_auth_status("wordpress")
            results["wordpress_auth"] = "passed" if wp_ok else f"failed: {wp_message}"
        except Exception as e:
            results["wordpress_auth"] = f"failed: {e}"

        try:
            notion_ok, notion_message = _active_profile_auth_status("notion")
            results["notion_auth"] = "passed" if notion_ok else f"failed: {notion_message}"
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
