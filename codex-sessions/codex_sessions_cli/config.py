"""Configuration management for CodexSessions CLI wrapper."""
import os
import shutil
from pathlib import Path
from typing import Iterable, List, Optional

from dotenv import set_key
from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType

from .parsers import SESSION_SUBDIRS


def dedupe_codex_roots(roots: Iterable[Path]) -> List[Path]:
    """Return normalized Codex roots in first-seen order."""
    deduped = []
    seen = set()
    for path in roots:
        absolute = Path(os.path.abspath(Path(path).expanduser()))
        key = os.path.normcase(str(absolute.resolve()))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(absolute)
    return deduped


def _codex_base_home(codex_home: Path) -> Path:
    """Treat a configured profile home as a child of its base Codex home."""
    parts = codex_home.expanduser().parts
    for index, part in enumerate(parts):
        if part == "profiles" and index + 2 == len(parts):
            return Path(*parts[:index])
    return codex_home.expanduser()


class Config(BaseConfig):
    """Configuration manager for CodexSessions CLI wrapper."""

    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DIST_NAME = "codex-sessions-cli"

    def __init__(self, profile=None):
        """Initialize configuration by loading from .env file."""
        super().__init__(tool_dir=resolve_tool_dir(self.DIST_NAME), profile=profile)

    @property
    def cli_command(self) -> str:
        """Get the underlying CLI command name."""
        return os.getenv("CLI_COMMAND", "codex")

    @property
    def cli_path(self) -> Optional[str]:
        """Get optional full path to CLI executable."""
        return os.getenv("CLI_PATH")

    @property
    def codex_home(self) -> Path:
        """Return the first discovered Codex root."""
        return self.codex_roots[0]

    @property
    def codex_roots(self) -> List[Path]:
        """Return the Codex roots read by the CLI in deterministic order."""
        explicit_home = os.getenv("CODEX_SESSIONS_CODEX_HOME", "").strip()
        if explicit_home:
            return dedupe_codex_roots([Path(explicit_home)])

        configured_home = os.getenv("CODEX_HOME", "").strip()
        base_home = _codex_base_home(
            Path(configured_home) if configured_home else Path.home() / ".codex"
        )

        profile = os.getenv("CODEX_SESSIONS_CODEX_PROFILE", "").strip()
        if profile:
            return dedupe_codex_roots([base_home / "profiles" / profile])

        roots = [base_home]
        profiles_dir = base_home / "profiles"
        if profiles_dir.is_dir():
            for profile_home in sorted(profiles_dir.iterdir(), key=lambda path: path.name):
                if profile_home.is_dir() and any(
                    (profile_home / subdir).exists() for subdir in SESSION_SUBDIRS
                ):
                    roots.append(profile_home)
        return dedupe_codex_roots(roots)

    def test_connection(self) -> dict:
        """Verify the local Codex transcript store is readable."""
        roots = self.codex_roots
        codex_home = roots[0]
        sessions_dir = codex_home / "sessions"
        exists = any(root.exists() for root in roots)
        return {
            "api_test": "passed" if exists else f"failed: {codex_home} does not exist",
            "codex_home": str(codex_home),
            "codex_roots": [str(root) for root in roots],
            "sessions_dir": str(sessions_dir),
            "sessions_dirs": [str(root / "sessions") for root in roots],
            "cli_command": self.cli_command,
            "cli_available": self.is_cli_available(),
            "cli_version": self.get_cli_version(),
        }

    def get_cli_executable(self) -> str:
        """Get the CLI executable path, falling back to command name."""
        if self.cli_path:
            return self.cli_path
        return self.cli_command

    def is_cli_available(self) -> bool:
        """Check if the underlying CLI is available in PATH."""
        return shutil.which(self.get_cli_executable()) is not None

    def get_cli_version(self) -> Optional[str]:
        """Get the version of the underlying CLI (if available)."""
        import subprocess
        try:
            result = subprocess.run(
                [self.get_cli_executable(), "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            return None
        return None

    def save_setting(self, key: str, value: str):
        """Save a setting to the .env file and update environment."""
        set_key(self.env_file_path, key, value)
        # Also update os.environ so subsequent reads get the new value
        os.environ[key] = value

    def clear_settings(self):
        """Clear all settings from .env file and environment."""
        # Track keys before clearing file
        if self.env_file_path.exists():
            # Read existing keys to clear from os.environ
            from dotenv import dotenv_values
            existing = dotenv_values(self.env_file_path)
            for key in existing:
                os.environ.pop(key, None)
            self.env_file_path.write_text("")


# Global config instance - singleton pattern
_config: Optional[Config] = None


def get_config(profile=None) -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None or profile is not None:
        _config = Config(profile=profile)
    return _config
