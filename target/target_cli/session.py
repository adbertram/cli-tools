"""Redsky session storage for the Target CLI.

Target's internal JSON API (redsky) authorizes on two cookies, ``_tgt_token``
and ``_tgt_session``, that PerimeterX only mints inside a real, visible browser
(see ``browser.py``'s ``prime_redsky``). Those cookies plus the long-lived
``visitorId`` are cached here as runtime auth state under the active profile so
that reads can run as plain httpx calls with no browser.

This is CLI-managed runtime auth state, so it lives in the profile data dir
(``authentication_profiles/<profile>/redsky_session.json``) per config-standards
-- NOT the secret manager (which is for reusable human-supplied credentials).
"""

import json
import time
from pathlib import Path
from typing import Optional

# _tgt_token is observed at ~24h TTL; refuse to trust one older than this so a
# read never fails mid-flight on a token that expired seconds ago.
SESSION_MAX_AGE_SECONDS = 23 * 3600

SESSION_FILENAME = "redsky_session.json"


class RedskySession:
    """A captured, verified redsky browser session."""

    __slots__ = ("tgt_token", "tgt_session", "visitor_id", "store_id", "zip", "captured_at")

    def __init__(self, tgt_token, tgt_session, visitor_id, store_id, zip, captured_at):
        self.tgt_token = tgt_token
        self.tgt_session = tgt_session
        self.visitor_id = visitor_id
        self.store_id = store_id
        self.zip = zip
        self.captured_at = captured_at

    @property
    def age_seconds(self) -> float:
        return time.time() - self.captured_at

    @property
    def expired(self) -> bool:
        return self.age_seconds > SESSION_MAX_AGE_SECONDS

    @property
    def cookies(self) -> dict:
        return {
            "_tgt_token": self.tgt_token,
            "_tgt_session": self.tgt_session,
            "visitorId": self.visitor_id,
        }

    def to_dict(self) -> dict:
        return {
            "tgt_token": self.tgt_token,
            "tgt_session": self.tgt_session,
            "visitor_id": self.visitor_id,
            "store_id": self.store_id,
            "zip": self.zip,
            "captured_at": self.captured_at,
        }


def session_path(config) -> Path:
    return config.get_profile_data_dir() / SESSION_FILENAME


def save_session(
    config, *, tgt_token: str, tgt_session: str, visitor_id: str, store_id: str, zip: str
) -> RedskySession:
    """Persist a freshly captured redsky session (0600) and return it."""
    session = RedskySession(
        tgt_token=tgt_token,
        tgt_session=tgt_session,
        visitor_id=visitor_id,
        store_id=store_id,
        zip=zip,
        captured_at=time.time(),
    )
    path = session_path(config)
    path.write_text(json.dumps(session.to_dict(), indent=2))
    path.chmod(0o600)
    return session


def load_session(config) -> Optional[RedskySession]:
    """Load the cached redsky session, or ``None`` if it was never captured."""
    path = session_path(config)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return RedskySession(
        tgt_token=data["tgt_token"],
        tgt_session=data["tgt_session"],
        visitor_id=data["visitor_id"],
        store_id=data["store_id"],
        zip=data["zip"],
        captured_at=data["captured_at"],
    )


def clear_session(config) -> None:
    path = session_path(config)
    if path.exists():
        path.unlink()
