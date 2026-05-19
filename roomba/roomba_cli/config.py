"""Configuration management for Roomba CLI.

Extends BaseConfig from cli_tools_shared for profile and credential management.
Robot-specific credentials (blid, password per robot) are stored in a separate
robots.json config file.
"""
import json
from pathlib import Path
from typing import Dict, Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Configuration for Roomba CLI.

    Robot discovery data is stored in a separate robots.json file.
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
        self._robots: Dict[str, dict] = {}
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
        """Save robot credentials to JSON file."""
        self._robots_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._robots_path, "w") as f:
            json.dump({"robots": self._robots}, f, indent=2)

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
    def robots(self) -> Dict[str, dict]:
        """Get all configured robots."""
        return self._robots.copy()

    @property
    def config_path(self) -> Path:
        """Get robots config file path."""
        return self._robots_path

    def get_robot(self, name_or_ip: str) -> Optional[dict]:
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

    def add_robot(
        self,
        name: str,
        ip: str,
        blid: str,
        password: str,
        mac: Optional[str] = None,
        sku: Optional[str] = None,
        software_ver: Optional[str] = None,
    ):
        """Add or update a robot's credentials."""
        self._robots[name] = {"ip": ip, "blid": blid, "password": password}
        if mac:
            self._robots[name]["mac"] = mac
        if sku:
            self._robots[name]["sku"] = sku
        if software_ver:
            self._robots[name]["software_ver"] = software_ver
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
_config: Optional[Config] = None


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
