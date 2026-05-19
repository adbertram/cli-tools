"""Internal types for log processing (dataclasses for parser internals).

These are NOT exposed via the CLI — they're used by parsers/discovery internally.
CLI output uses the Pydantic models from models/item.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..models import ContainerType, Entity


@dataclass(frozen=True)
class FileMetadata:
    """Metadata extracted from a Docker log filename."""
    date: str              # "2026_02_10"
    instance: str          # "lw0sdlwk0004PO"
    container_type: ContainerType
    rotation: Optional[int]   # .1, .2 suffix or None


@dataclass(frozen=True)
class ClassifiedLogFile:
    """A log file classified by entity with its metadata."""
    path: Path
    relative_path: str     # Relative to log package root
    entity: Entity
    metadata: Optional[FileMetadata]  # None for non-Docker logs


@dataclass(frozen=True)
class LineRange:
    """A contiguous range of raw lines covered by one LogEntry."""
    source_file: str
    start_line: int        # 1-indexed, inclusive
    end_line: int          # 1-indexed, inclusive


@dataclass
class InternalLogEntry:
    """Internal log entry used by parsers before conversion to Pydantic model.

    Using a dataclass avoids Pydantic validation overhead during bulk parsing.
    """
    timestamp: datetime
    entity: Entity
    service: str
    instance: Optional[str]
    container: Optional[str]
    level: "LogLevel"  # forward ref to avoid circular import
    message: str
    source_file: str
    line_number: int
    session_id: Optional[str] = None  # assigned after parsing by session detection

    def to_dict(self) -> dict:
        """Convert to dict for Pydantic model creation."""
        return {
            "timestamp": self.timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
            "entity": self.entity,
            "service": self.service,
            "instance": self.instance,
            "container": self.container,
            "level": self.level,
            "message": self.message,
            "source_file": self.source_file,
            "line_number": self.line_number,
            "session_id": self.session_id,
        }


@dataclass
class Session:
    """A container lifecycle session — from start to stop.

    Tracks the container lifecycle (create → start → stop → delete) and
    any app-level events (e.g. 'Application started') within that window.
    """
    id: str                          # e.g. "session-001"
    container_name: Optional[str]    # e.g. "5f79b5b70c23_devolutions-ciem-psu"
    instance: Optional[str]          # e.g. "lw0sdlwk0004PO"
    start_time: datetime
    end_time: Optional[datetime]     # None if session is still open
    events: list[dict]               # lifecycle events: [{type, timestamp, message}]
    entry_count: int = 0             # total log entries assigned to this session


@dataclass
class InternalValidationResult:
    """Internal validation result before conversion to Pydantic model."""
    total_raw_lines: int
    total_covered_lines: int
    missing_lines: list  # [(file, line_number)]
    is_valid: bool
