"""Session detection: group log entries into container lifecycle sessions.

A session spans from container start to container stop. Log entries are
assigned to sessions by matching instance + timestamp range. Entries
without an instance are matched by timestamp range alone.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from ..models import Entity
from .types import InternalLogEntry, Session

# --- Lifecycle event patterns (matched against platform_orchestrator messages) ---

_CREATING_RE = re.compile(r"^Creating container\.$")
_CREATING_IMAGE_RE = re.compile(r"^Creating container with image: (.+) from registry:")
_STARTING_RE = re.compile(r"^Starting container: (.+)\.$")
_STOPPING_RE = re.compile(r"^Stopping container: (.+)\.$")
_DELETING_RE = re.compile(r"^Deleting container: (.+)\.")

# --- App-level lifecycle patterns (matched against app_container / scm_sidecar messages) ---

_APP_STARTED_RE = re.compile(r"Application started")
_APP_LISTENING_RE = re.compile(r"Now listening on: (.+)")
_APP_SHUTDOWN_RE = re.compile(r"Application is shutting down|Hosting shutdown")


def _make_event(event_type: str, timestamp: datetime, message: str) -> dict:
    """Create a lifecycle event dict."""
    return {
        "type": event_type,
        "timestamp": timestamp,
        "message": message,
    }


def detect_sessions(entries: list[InternalLogEntry]) -> list[Session]:
    """Detect container lifecycle sessions from sorted log entries.

    Scans platform_orchestrator entries for container start/stop events
    to define session boundaries. Returns sessions sorted by start_time.
    """
    # Phase 1: Build sessions from platform orchestrator lifecycle events
    open_sessions: dict[str, Session] = {}  # keyed by instance (only one active per instance)
    sessions: list[Session] = []
    session_counter = 0

    for entry in entries:
        if entry.entity is not Entity.PLATFORM_ORCHESTRATOR:
            continue

        msg = entry.message
        instance = entry.instance

        # "Creating container." — signals a new session is about to start
        if _CREATING_RE.match(msg):
            # If there's already an open session for this instance, close it
            if instance and instance in open_sessions:
                old = open_sessions.pop(instance)
                old.end_time = entry.timestamp
                sessions.append(old)

            session_counter += 1
            sid = f"session-{session_counter:03d}"
            session = Session(
                id=sid,
                container_name=None,
                instance=instance,
                start_time=entry.timestamp,
                end_time=None,
                events=[_make_event("container_creating", entry.timestamp, msg)],
            )
            if instance:
                open_sessions[instance] = session
            continue

        # "Starting container: X." — marks the container name
        m = _STARTING_RE.match(msg)
        if m and instance and instance in open_sessions:
            session = open_sessions[instance]
            session.container_name = m.group(1)
            session.events.append(_make_event("container_started", entry.timestamp, msg))
            continue

        # "Stopping container: X."
        m = _STOPPING_RE.match(msg)
        if m and instance and instance in open_sessions:
            session = open_sessions[instance]
            session.events.append(_make_event("container_stopping", entry.timestamp, msg))
            continue

        # "Deleting container: X." — session is ending
        m = _DELETING_RE.match(msg)
        if m and instance and instance in open_sessions:
            session = open_sessions.pop(instance)
            session.end_time = entry.timestamp
            session.events.append(_make_event("container_deleted", entry.timestamp, msg))
            sessions.append(session)
            continue

    # Close any sessions that never got a stop/delete event
    for session in open_sessions.values():
        sessions.append(session)

    sessions.sort(key=lambda s: s.start_time)
    return sessions


def assign_entries_to_sessions(
    entries: list[InternalLogEntry],
    sessions: list[Session],
) -> None:
    """Assign each log entry to a session by matching instance + timestamp range.

    Mutates entries in place, setting session_id. Also detects app-level
    lifecycle events and appends them to the session's events list.
    """
    if not sessions:
        return

    # Build lookup: instance -> list of sessions (sorted by start_time)
    by_instance: dict[Optional[str], list[Session]] = {}
    for s in sessions:
        by_instance.setdefault(s.instance, []).append(s)

    # Also keep a flat list for timestamp-only matching (entries without instance)
    all_sessions = sorted(sessions, key=lambda s: s.start_time)

    for entry in entries:
        session = _find_session(entry, by_instance, all_sessions)
        if session:
            entry.session_id = session.id
            session.entry_count += 1

            # Detect app-level lifecycle events within sessions
            _detect_app_event(entry, session)


def _find_session(
    entry: InternalLogEntry,
    by_instance: dict[Optional[str], list[Session]],
    all_sessions: list[Session],
) -> Optional[Session]:
    """Find the session an entry belongs to."""
    ts = entry.timestamp

    # Try instance-specific match first
    if entry.instance:
        candidates = by_instance.get(entry.instance, [])
        for s in candidates:
            end = s.end_time or datetime.max
            if s.start_time <= ts <= end:
                return s

    # Fall back to timestamp-only match (for entries without instance)
    for s in all_sessions:
        end = s.end_time or datetime.max
        if s.start_time <= ts <= end:
            return s

    return None


def _detect_app_event(entry: InternalLogEntry, session: Session) -> None:
    """Check if an entry is an app-level lifecycle event and record it."""
    if entry.entity not in (Entity.APP_CONTAINER, Entity.SCM_SIDECAR):
        return

    msg = entry.message
    if _APP_STARTED_RE.search(msg):
        session.events.append(_make_event("app_started", entry.timestamp, msg))
    elif _APP_LISTENING_RE.search(msg):
        session.events.append(_make_event("app_listening", entry.timestamp, msg))
    elif _APP_SHUTDOWN_RE.search(msg):
        session.events.append(_make_event("app_shutdown", entry.timestamp, msg))
