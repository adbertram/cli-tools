"""Configuration for the BrickStore MCP client."""

from cli_tools_shared.config import BaseConfig, resolve_tool_dir


class Config(BaseConfig):
    """Resolve BrickStore non-secret runtime configuration."""

    DIST_NAME = "brickstore-cli"
    CREDENTIAL_TYPES = []
    DEFAULT_BASE_URL = "http://127.0.0.1:45111"
    DEFAULT_EXECUTABLE = "/Applications/BrickStore.app/Contents/MacOS/BrickStore"
    CUSTOM_ALL_FIELDS = ["BRICKSTORE_BASE_URL", "BRICKSTORE_EXECUTABLE"]
    ROOT_CONFIG_FIELDS = ("BRICKSTORE_BASE_URL", "BRICKSTORE_EXECUTABLE")

    def __init__(self, profile=None):
        super().__init__(tool_dir=resolve_tool_dir(self.DIST_NAME), profile=profile)

    @property
    def base_url(self):
        """Return the dedicated BrickStore MCP endpoint."""
        return self._get("BRICKSTORE_BASE_URL") or self.DEFAULT_BASE_URL

    @property
    def executable(self):
        """Return the BrickStore executable path."""
        return self._get("BRICKSTORE_EXECUTABLE") or self.DEFAULT_EXECUTABLE


_configs = {}


def get_config(profile=None):
    """Return the profile-scoped configuration instance."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
