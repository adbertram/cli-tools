"""Configuration for the Grok Bot session CLI.

Grok Bot owns the session: this CLI only reads the account Grok Bot's desktop
app is already signed in to. There is no CLI-minted credential and nothing
secret is ever written to a profile ``.env``; a profile exists so the shared
``auth`` command group can report the live connection per profile.
"""
import json
import os
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType

DEFAULT_CLIENT_VERSION = "0.47.0"

APP_DIR_ENV = "GROKBOT_SESSIONS_APP_DIR"
API_BASE_ENV = "GROKBOT_SESSIONS_API_BASE"


class Config(BaseConfig):
    """Resolve Grok Bot app paths, API base, and live connection status."""

    DIST_NAME = "grokbot-sessions-cli"
    # The credential lives in the Grok Bot app, not in this CLI. CUSTOM keeps
    # the shared auth contract (per-profile JSON status) without declaring a
    # CLI-owned secret field, so ``auth login`` adopts rather than stores.
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DEFAULT_BASE_URL = "https://api2.cursor.sh"
    AUTH_SETUP_INSTRUCTIONS = (
        "grokbot-sessions adopts the session the Grok Bot desktop app already holds.\n"
        "  1. Open Grok Bot and sign in (the CLI cannot mint a token).\n"
        "  2. Then run 'grokbot-sessions auth login' to verify the live connection."
    )

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def app_dir(self) -> Path:
        """Grok Bot's user-data directory."""
        configured = os.getenv(APP_DIR_ENV)
        if configured and configured.strip():
            return Path(configured.strip()).expanduser()
        return Path.home() / "Library" / "Application Support" / "Grok Bot"

    @property
    def secrets_path(self) -> Path:
        """Grok Bot's credential store."""
        return self.app_dir / "sand-secrets.json"

    @property
    def desktop_status_path(self) -> Path:
        """Grok Bot's desktop status file (app version and connection state)."""
        return self.app_dir / "desktop-status.json"

    @property
    def api_base_url(self) -> str:
        """Connect RPC base URL, overridable for local debugging."""
        override = os.getenv(API_BASE_ENV)
        if override and override.strip():
            return override.strip().rstrip("/")
        return self.base_url.rstrip("/")

    @property
    def client_version(self) -> str:
        """The ``x-cursor-client-version`` value Grok Bot itself sends."""
        try:
            document = json.loads(self.desktop_status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return DEFAULT_CLIENT_VERSION
        version = document.get("appVersion") if isinstance(document, dict) else None
        return str(version) if version else DEFAULT_CLIENT_VERSION

    def test_connection(self) -> dict:
        """Verify the adopted session with a live ``ListGrokBotAgents`` call."""
        from .client import GrokBotClient

        try:
            agents = GrokBotClient(config=self).list_agents(limit=1)
        except Exception as exc:
            # Reported through the shared per-credential-type auth status shape.
            return {"api_test": f"failed: {exc}"}
        return {
            "api_test": "passed",
            "agent_count": len(agents),
            "app_dir": str(self.app_dir),
            "client_version": self.client_version,
        }


_configs = {}


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create a config for a profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
