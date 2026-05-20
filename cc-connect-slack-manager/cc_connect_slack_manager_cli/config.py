"""Configuration management for the cc-connect Slack manager CLI."""
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType

from .client import CcConnectSlackManagerClient


class Config(BaseConfig):
    """Configuration for local cc-connect Slack bridge checks."""

    DIST_NAME = "cc-connect-slack-manager-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS = []
    CUSTOM_ALL_FIELDS = []
    CUSTOM_EPHEMERAL_FIELDS = []

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )
        self._ensure_repo_default_env_stub()

    def test_connection(self) -> dict:
        """Verify the local Cody bridge configuration can be loaded."""
        try:
            client = CcConnectSlackManagerClient(config=self)
        except Exception as exc:
            return {"api_test": f"failed: {exc}"}

        return {
            "api_test": "passed",
            "config_path": str(client.config_path),
            "wrapper_path": str(client.wrapper_path),
        }

    def _ensure_repo_default_env_stub(self) -> None:
        """Keep a repo-local default profile stub for compliance profile tests."""
        repo_env = self.tool_dir / ".env"
        if not repo_env.exists():
            repo_env.write_text("IS_DEFAULT_PROFILE=1\n")


_config: Optional[Config] = None


def get_config(profile=None) -> Config:
    """Return the config singleton for the active profile."""
    global _config
    if _config is None or profile is not None:
        _config = Config(profile=profile)
    return _config
