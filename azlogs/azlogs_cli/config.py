"""Configuration management for Azlogs CLI.

Auth delegates to the upstream `az` CLI. App name and resource group are
passed as CLI params — no persistent credential storage.
"""
import json
import subprocess
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Azlogs CLI configuration (delegates auth to `az` CLI)."""

    DIST_NAME = "azlogs-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS: list = []  # no local credentials — lives in `az`

    LOGIN_INSTRUCTIONS = (
        "Azlogs delegates authentication to the Azure CLI (`az`).\n"
        "  1. Install az: https://learn.microsoft.com/en-us/cli/azure/install-azure-cli\n"
        "  2. Run: az login"
    )

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )
        # app/rg are set per-invocation via CLI params, not persisted
        self._app_name: Optional[str] = self._get("AZLOGS_APP_NAME")
        self._resource_group: Optional[str] = self._get("AZLOGS_RESOURCE_GROUP")

    @property
    def app_name(self) -> Optional[str]:
        """Azure Web App name (set via CLI --app flag or .env)."""
        return self._app_name

    @app_name.setter
    def app_name(self, value: str):
        self._app_name = value

    @property
    def resource_group(self) -> Optional[str]:
        """Azure Resource Group name (set via CLI --resource-group flag or .env)."""
        return self._resource_group

    @resource_group.setter
    def resource_group(self, value: str):
        self._resource_group = value

    @property
    def data_dir(self) -> Path:
        """Directory for downloaded log packages."""
        return self.tool_dir / "data"

    def test_connection(self) -> Optional[dict]:
        """Verify upstream `az` CLI is installed and authenticated.

        Azlogs has no credentials of its own — it relies on `az` for Azure
        authentication. We probe `az account show` and report pass/fail.
        """
        try:
            out = subprocess.run(
                ["az", "account", "show", "--output", "json"],
                capture_output=True, text=True, check=True, timeout=30,
            ).stdout
            account = json.loads(out)
            return {
                "api_test": "passed",
                "upstream": "az",
                "subscription": account.get("name", ""),
                "user": account.get("user", {}).get("name", ""),
            }
        except FileNotFoundError:
            return {"api_test": "failed: az CLI not installed", "upstream": "az"}
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip().splitlines()[-1] if e.stderr else str(e)
            return {"api_test": f"failed: upstream az not authenticated ({stderr})", "upstream": "az"}
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            return {"api_test": f"failed: {e}", "upstream": "az"}


_configs: dict = {}


def get_config(profile=None) -> Config:
    """Get or create a config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
