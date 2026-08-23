"""Configuration for the BrickStore MCP client."""

from cli_tools_shared.config import BaseConfig, resolve_tool_dir

from .database import DATABASE_FILE_NAME


class Config(BaseConfig):
    """Resolve BrickStore non-secret runtime configuration."""

    DIST_NAME = "brickstore-cli"
    CREDENTIAL_TYPES = []
    DEFAULT_BASE_URL = "http://127.0.0.1:45111"
    DEFAULT_EXECUTABLE = "/Applications/BrickStore.app/Contents/MacOS/BrickStore"
    DEFAULT_DATABASE_PATH = "~/Library/Caches/BrickStore/{}".format(DATABASE_FILE_NAME)
    DEFAULT_DATABASE_URL = "https://github.com/rgriebl/brickstore-database/releases/latest/download"
    CUSTOM_ALL_FIELDS = [
        "BRICKSTORE_BASE_URL",
        "BRICKSTORE_EXECUTABLE",
        "BRICKSTORE_DATABASE_PATH",
        "BRICKSTORE_DATABASE_URL",
    ]
    ROOT_CONFIG_FIELDS = (
        "BRICKSTORE_BASE_URL",
        "BRICKSTORE_EXECUTABLE",
        "BRICKSTORE_DATABASE_PATH",
        "BRICKSTORE_DATABASE_URL",
    )

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

    @property
    def database_path(self):
        """Return the local BrickStore catalog database path."""
        return self._get("BRICKSTORE_DATABASE_PATH") or self.DEFAULT_DATABASE_PATH

    @property
    def database_url(self):
        """Return the base URL that publishes the BrickStore catalog database."""
        return self._get("BRICKSTORE_DATABASE_URL") or self.DEFAULT_DATABASE_URL


_configs = {}


def get_config(profile=None):
    """Return the profile-scoped configuration instance."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
