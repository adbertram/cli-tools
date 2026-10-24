"""Configuration management for Roomba CLI.

Extends BaseConfig from cli_tools_shared for profile and credential management.
Robot-specific credentials (blid, password per robot) are stored in a separate
robots.json config file with restricted permissions.
"""
import json
import os
import stat
from pathlib import Path

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for Roomba CLI.

    Robot discovery data is stored in a separate robots.json file.
    Each robot has a 'selected' field (true/false). The selected robot
    is used when no robot name is specified.
    """

    DIST_NAME = "roomba-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS: list[str] = []
    CUSTOM_ALL_FIELDS: list[str] = []

    def __init__(self, tool_dir: Path = None, profile: str = None):
        if tool_dir is None:
            tool_dir = resolve_tool_dir(self.DIST_NAME)
        super().__init__(tool_dir, profile=profile)
        self._robots_path = self.get_profile_data_dir() / "robots.json"
        self._robots: dict[str, dict] = {}
        self._load_robots()

    def _load_robots(self):
        """Load robot credentials from JSON file."""
        if self._robots_path.exists():
            try:
                with open(self._robots_path, "r") as f:
                    data = json.load(f)
                    self._robots = data.get("robots", {})
            except (json.JSONDecodeError, IOError):
                self._robots = {}

    def _save_robots(self):
        """Save robot credentials to JSON file with restricted permissions."""
        parent = self._robots_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        fd = open(self._robots_path, "w")
        try:
            os.fchmod(fd.fileno(), stat.S_IRUSR | stat.S_IWUSR)
        except (OSError, AttributeError):
            pass  # fchmod not supported on all platforms
        json.dump({"robots": self._robots}, fd, indent=2)
        fd.close()

    def has_credentials(self) -> bool:
        """Check if any robot credentials are configured."""
        return len(self._robots) > 0

    def get_missing_credentials(self) -> list[str]:
        """Get list of missing credentials."""
        if not self._robots:
            return ["No robots configured"]
        return []

    def test_connection(self) -> dict:
        """Test connection by checking if robots are configured."""
        if self._robots:
            return {"api_test": "passed", "robots_configured": len(self._robots)}
        return {"api_test": "failed: No robots configured"}

    @property
    def robots(self) -> dict[str, dict]:
        """Get all configured robots."""
        return self._robots.copy()

    @property
    def config_path(self) -> Path:
        """Get robots config file path."""
        return self._robots_path

    def get_robot(self, name_or_ip: str) -> dict | None:
        """Get robot credentials by name or IP."""
        if name_or_ip in self._robots:
            robot = self._robots[name_or_ip].copy()
            robot["name"] = name_or_ip
            return robot
        for name, robot in self._robots.items():
            if robot.get("ip") == name_or_ip:
                result = robot.copy()
                result["name"] = name
                return result
        return None

    def get_default_robot(self) -> str | None:
        """Return the first robot with selected=true, or None."""
        for name, data in self._robots.items():
            if data.get("selected") is True:
                return name
        return None

    def set_selected(self, name: str):
        """Mark a robot as selected. All others are deselected."""
        for rname in self._robots:
            self._robots[rname]["selected"] = (rname == name)
        self._save_robots()

    def add_robot(
        self,
        name: str,
        ip: str,
        blid: str,
        password: str,
        mac: str | None = None,
        sku: str | None = None,
        software_ver: str | None = None,
    ):
        """Add or update a robot's credentials."""
        self._robots[name] = {"ip": ip, "blid": blid, "password": password}
        if mac:
            self._robots[name]["mac"] = mac
        if sku:
            self._robots[name]["sku"] = sku
        if software_ver:
            self._robots[name]["software_ver"] = software_ver
        # Set as selected only if this is the first robot
        if len(self._robots) == 1:
            self._robots[name]["selected"] = True
        else:
            # Deselect all others to make this one the default
            for rname in self._robots:
                self._robots[rname]["selected"] = (rname == name)
        self._save_robots()

    def remove_robot(self, name: str) -> bool:
        """Remove a robot's credentials."""
        if name in self._robots:
            del self._robots[name]
            self._save_robots()
            return True
        return False

    def clear_all_robots(self):
        """Clear all robot credentials."""
        self._robots = {}
        self._save_robots()

    def robot_count(self) -> int:
        """Get number of configured robots."""
        return len(self._robots)


# Global config instance
_config: Config | None = None


def get_config(profile: str = None) -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None or profile is not None:
        _config = Config(profile=profile)
    return _config


def reset_config():
    """Reset the global config instance (for testing)."""
    global _config
    _config = None
