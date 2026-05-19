"""Configuration management for ShopSalvationArmy CLI."""
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """ShopSalvationArmy CLI configuration."""

    DIST_NAME = "shopsalvationarmy-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS = [
        "SHOPSALVATIONARMY_USERNAME",
        "SHOPSALVATIONARMY_PASSWORD",
    ]
    CUSTOM_ALL_FIELDS = [
        "SHOPSALVATIONARMY_USERNAME",
        "SHOPSALVATIONARMY_PASSWORD",
    ]
    CUSTOM_LOGIN_PROMPTS = [
        ("SHOPSALVATIONARMY_USERNAME", "Shop Salvation Army username/email", False),
        ("SHOPSALVATIONARMY_PASSWORD", "Shop Salvation Army password", True),
    ]
    CUSTOM_SENSITIVE_FIELDS = ["SHOPSALVATIONARMY_PASSWORD"]

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def username(self) -> Optional[str]:
        """Get ShopSalvationArmy username."""
        return self._get("SHOPSALVATIONARMY_USERNAME")

    @property
    def password(self) -> Optional[str]:
        """Get ShopSalvationArmy password."""
        return self._get("SHOPSALVATIONARMY_PASSWORD")

    def save_credentials(self, username: str, password: str):
        """Save username and password to the active profile."""
        self._set("SHOPSALVATIONARMY_USERNAME", username)
        self._set("SHOPSALVATIONARMY_PASSWORD", password)

    def test_connection(self) -> Optional[dict]:
        """Verify Shop Salvation Army credentials by logging in."""
        from .client import ClientError, ShopSalvationArmyClient

        try:
            result = ShopSalvationArmyClient(require_auth=False, config=self).login(
                self.username,
                self.password,
            )
        except ClientError as e:
            return {"api_test": f"failed: {e}"}

        if result.get("authenticated"):
            return {"api_test": "passed", "username": self.username}
        return {"api_test": "failed: login response was not authenticated"}


_configs: dict = {}


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create a config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
