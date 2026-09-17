"""Configuration management for AtaBlog CLI."""
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
    """Configuration for AtaBlog CLI.

    Authentication is delegated to the notion CLI. Uses the CUSTOM credential
    type with no local credentials stored.
    """

    DIST_NAME = "ata-blog-cli"

    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS = []
    CUSTOM_ALL_FIELDS = []
    CUSTOM_LOGIN_PROMPTS = []
    CUSTOM_EPHEMERAL_FIELDS = []
    CUSTOM_SENSITIVE_FIELDS = []
    ROOT_CONFIG_FIELDS = ("NOTION_DATABASE_ID",)

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def notion_database_id(self) -> str:
        """Get the Notion database ID for articles."""
        return self._get("NOTION_DATABASE_ID") or "2a317112-d9c8-42ee-a4d4-a2b8a5a20818"

    def is_notion_available(self) -> bool:
        """Check if notion CLI is available."""
        import shutil
        return shutil.which("notion") is not None

    def has_credentials(self) -> bool:
        """Check if the notion CLI has saved credentials in its active profile."""
        try:
            return _active_profile_has_credentials("notion")
        except Exception:
            return False

    def test_connection(self) -> dict:
        """Test connectivity to the notion CLI."""
        try:
            notion_ok, notion_message = _active_profile_auth_status("notion")
            notion_auth = "passed" if notion_ok else f"failed: {notion_message}"
        except Exception as e:
            notion_auth = f"failed: {e}"

        return {
            "notion_auth": notion_auth,
            "api_test": (
                "passed" if notion_auth == "passed"
                else "failed: notion CLI not authenticated"
            ),
        }


_config: Optional[Config] = None


def get_config(profile=None) -> Config:
    """Get or create config instance."""
    global _config
    if _config is None or profile is not None:
        _config = Config(profile=profile)
    return _config
