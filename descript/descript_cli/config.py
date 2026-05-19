"""Configuration management for Descript CLI."""
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Descript CLI configuration (JWT extracted from running app)."""

    DIST_NAME = "descript-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DEFAULT_BASE_URL = "https://web.descript.com"
    CUSTOM_REQUIRED_FIELDS: list = []
    CUSTOM_ALL_FIELDS = ["DESCRIPT_BASE_URL"]

    LOGIN_INSTRUCTIONS = (
        "Descript authentication is extracted from the running Descript app.\n"
        "Open Descript before running 'descript auth login'."
    )

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def base_url(self) -> str:
        return self._get("DESCRIPT_BASE_URL") or self.DEFAULT_BASE_URL

    def get_missing_credentials(self) -> list[str]:
        return []

    def test_connection(self) -> Optional[dict]:
        """Verify a JWT can be read from cache or the running app."""
        from .client import DescriptClient, ClientError
        try:
            jwt = DescriptClient(config=self)._get_jwt()
            return {
                "api_test": "passed",
                "token_preview": f"{jwt[:20]}..." if len(jwt) > 20 else "***",
            }
        except ClientError as e:
            return {"api_test": f"failed: {e}"}


_configs: dict = {}


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create a config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
