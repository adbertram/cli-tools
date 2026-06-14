"""Configuration management for Harmony CLI."""

from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.exceptions import ClientError


class Config(BaseConfig):
    DIST_NAME = "harmony-cli"
    CREDENTIAL_TYPES = []
    DEFAULT_BASE_URL = "harmony://local"
    CUSTOM_ALL_FIELDS = [
        "HARMONY_HUB",
        "HARMONY_PROTOCOL",
        "HARMONY_DISCOVERY_TIMEOUT",
    ]
    ROOT_CONFIG_FIELDS = (
        "HARMONY_HUB",
        "HARMONY_PROTOCOL",
        "HARMONY_DISCOVERY_TIMEOUT",
    )

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def storage_dir(self) -> Path:
        """Profile-aware storage directory for runtime state."""
        return self.get_profile_data_dir()

    @property
    def default_hub(self) -> Optional[str]:
        """Default hub IP address, hostname, or Bonjour name."""
        return self._get("HARMONY_HUB")

    @property
    def default_protocol(self) -> str:
        """Default Harmony protocol."""
        return (self._get("HARMONY_PROTOCOL") or "WEBSOCKETS").upper()

    @property
    def discovery_timeout(self) -> float:
        """Bonjour discovery timeout in seconds."""
        value = self._get("HARMONY_DISCOVERY_TIMEOUT")
        if not value:
            return 3.0
        try:
            return float(value)
        except ValueError as exc:
            raise ClientError("HARMONY_DISCOVERY_TIMEOUT must be a number") from exc

    def test_connection(self) -> dict:
        """Validate local hub access with a live discovery probe."""
        from .client import HarmonyClient

        try:
            hubs = HarmonyClient(config=self).list_hubs(limit=1)
            return {"harmony_test": "passed", "hub_count": len(hubs)}
        except ClientError as exc:
            return {"harmony_test": f"failed: {exc}"}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
