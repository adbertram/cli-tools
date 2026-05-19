"""Configuration management for CourseCraft CLI."""
import json
import subprocess
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """CourseCraft CLI configuration.

    CourseCraft stores data in Airtable, so this CLI keeps its own base ID and
    verifies authentication through the underlying `airtable` CLI.
    """

    DIST_NAME = "coursecraft-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS = ["AIRTABLE_BASE_ID"]
    CUSTOM_ALL_FIELDS = ["AIRTABLE_BASE_ID"]
    CUSTOM_LOGIN_PROMPTS = [
        ("AIRTABLE_BASE_ID", "Airtable Base ID for CourseCraft", False),
    ]

    LOGIN_INSTRUCTIONS = (
        "CourseCraft uses Airtable for storage. Run `airtable auth login` if "
        "the underlying Airtable CLI is not authenticated."
    )

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def airtable_base_id(self) -> Optional[str]:
        """Get Airtable base ID for CourseCraft."""
        return self._get("AIRTABLE_BASE_ID")

    @property
    def storage_dir(self) -> Path:
        """Storage directory for cache and runtime data."""
        return self.get_profile_data_dir()

    def test_connection(self) -> Optional[dict]:
        """Verify Airtable CLI auth and CourseCraft base access."""
        status = self._run_airtable(["auth", "status"], timeout=30)
        if status.returncode != 0:
            return {"api_test": f"failed: {status.stderr.strip() or status.stdout.strip()}"}

        try:
            data = json.loads(status.stdout)
        except json.JSONDecodeError:
            return {"api_test": "failed: airtable auth status returned invalid JSON"}

        authenticated = bool(data.get("authenticated"))
        if "profiles" in data:
            authenticated = any(bool(profile.get("authenticated")) for profile in data["profiles"])

        if not authenticated:
            return {"api_test": "failed: airtable CLI is not authenticated"}

        records = self._run_airtable(
            ["records", "list", "Courses", "--base", self.airtable_base_id],
            timeout=30,
        )
        if records.returncode != 0:
            return {"api_test": f"failed: {records.stderr.strip() or records.stdout.strip()}"}

        return {
            "api_test": "passed",
            "airtable_cli": "authenticated",
            "base_id": self.airtable_base_id,
        }

    def _run_airtable(self, args: list[str], timeout: int) -> subprocess.CompletedProcess:
        """Run an Airtable CLI command."""
        try:
            return subprocess.run(
                ["airtable"] + args,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            return subprocess.CompletedProcess(args=["airtable"] + args, returncode=127, stderr="airtable CLI not found")
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(args=["airtable"] + args, returncode=124, stderr="airtable CLI timed out")


_configs: dict = {}


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create a config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
