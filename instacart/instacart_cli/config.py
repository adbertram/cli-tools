"""Configuration management for Instacart CLI."""
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """Instacart CLI configuration."""

    DIST_NAME = "instacart-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS: list[str] = []
    CUSTOM_ALL_FIELDS: list[str] = []

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )
        self.session_path = self.get_profile_data_dir() / "session.json"
        self.legacy_session_path = self.tool_dir / "instacart_cli" / "session.json"
        self._session: Optional[Dict[str, Any]] = None
        self._migrate_legacy_session_if_needed()

    def _migrate_legacy_session_if_needed(self):
        """Copy a legacy repo-local session capture into the profile data dir."""
        if self.session_path.exists() or not self.legacy_session_path.exists():
            return

        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.legacy_session_path, self.session_path)

    @property
    def session(self) -> Optional[Dict[str, Any]]:
        """Load and cache session data from session.json."""
        if self._session is None and self.session_path.exists():
            with open(self.session_path) as f:
                self._session = json.load(f)
        return self._session

    @property
    def graphql_endpoint(self) -> str:
        """Get GraphQL endpoint URL."""
        if self.session and "graphql_endpoint" in self.session:
            return self.session["graphql_endpoint"]
        return "https://www.instacart.com/graphql"

    @property
    def cookies(self) -> List[Dict[str, Any]]:
        """Get browser cookies for authentication."""
        if self.session and "cookies" in self.session:
            return self.session["cookies"]
        return []

    @property
    def persisted_queries(self) -> Dict[str, Dict[str, Any]]:
        """Get persisted query hashes and default variables."""
        if self.session and "persisted_queries" in self.session:
            return self.session["persisted_queries"]
        return {}

    @property
    def captured_at(self) -> Optional[str]:
        """Get session capture timestamp."""
        if self.session:
            return self.session.get("captured_at")
        return None

    def has_credentials(self) -> bool:
        """Check if valid session cookies are available."""
        if not self.session_path.exists():
            return False

        cookies = self.cookies
        if not cookies:
            return False

        cookie_names = {cookie.get("name") for cookie in cookies}
        essential_cookies = {"__Host-instacart_sid", "_instacart_session_id"}
        return bool(essential_cookies & cookie_names)

    def get_missing_credentials(self) -> list[str]:
        """Get list of missing credentials."""
        if self.has_credentials():
            return []
        return [f"session.json at {self.session_path}"]

    def get_cookie_header(self) -> str:
        """Build Cookie header string from stored cookies."""
        cookies = self.cookies
        if not cookies:
            return ""
        return "; ".join(f"{cookie['name']}={cookie['value']}" for cookie in cookies)

    def is_session_expired(self) -> bool:
        """Check if session cookies have expired."""
        cookies = self.cookies
        if not cookies:
            return True

        now = datetime.now().timestamp()
        for cookie in cookies:
            if cookie.get("name") in ["__Host-instacart_sid", "_instacart_session_id"]:
                expires = cookie.get("expires", -1)
                if expires > 0 and expires < now:
                    return True
        return False

    def save_session(self, session_data: Dict[str, Any]):
        """Save session data to session.json."""
        session_data["captured_at"] = datetime.utcnow().isoformat() + "Z"
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.session_path, "w") as f:
            json.dump(session_data, f, indent=2)
        self._session = session_data

    def clear_credentials(self):
        """Clear session file."""
        if self.session_path.exists():
            self.session_path.unlink()
        self._session = None

    def test_connection(self) -> Optional[dict]:
        """Verify stored Instacart browser session state with a live API call."""
        if self.is_session_expired():
            return {"api_test": "failed: session expired"}

        from .client import ClientError, InstacartClient

        try:
            user = InstacartClient(config=self).get_user()
            return {
                "api_test": "passed",
                "captured_at": self.captured_at,
                "session_file": str(self.session_path),
                "user_id": user.get("user_id"),
            }
        except ClientError as e:
            return {
                "api_test": f"failed: {e}",
                "captured_at": self.captured_at,
                "session_file": str(self.session_path),
            }


_configs: dict = {}


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create a config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
