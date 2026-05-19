"""Models for Azure Web App log entries, packages, and files.

Enums are shared between CLI output and internal processing.
Pydantic models provide type-safe CLI output with validation.
"""
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import Field

from .base import CLIModel


# ==================== Enums ====================


class Entity(str, Enum):
    """Infrastructure entity that produced the log."""
    PLATFORM_ORCHESTRATOR = "platform_orchestrator"
    APP_CONTAINER = "app_container"
    SCM_SIDECAR = "scm_sidecar"
    APP_LOG = "app_log"
    KUDU_TRACE = "kudu_trace"


class LogLevel(str, Enum):
    """Normalized log level."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class ContainerType(str, Enum):
    """Docker log file container type (from filename)."""
    PLATFORM = "platform"
    APP = "app"
    SCM = "scm"


class OutputFormat(str, Enum):
    """Output file format for merged logs."""
    JSONL = "jsonl"
    CSV = "csv"


# ==================== Models ====================


class LogEntry(CLIModel):
    """Single logical log entry (may span multiple raw lines).

    This is the primary data model — each parsed log line becomes a LogEntry.
    """
    # Required fields — always present
    timestamp: str  # ISO 8601 string for JSON serialization
    entity: Entity
    service: str
    level: LogLevel
    message: str
    source_file: str
    line_number: int

    # Optional fields — may be None for some entity types
    instance: Optional[str] = None
    container: Optional[str] = None


class LogFile(CLIModel):
    """A discovered and classified log file within a package."""
    path: str  # Relative path within the package
    entity: Entity
    size_bytes: int = 0
    container_type: Optional[ContainerType] = None
    date: Optional[str] = None
    instance: Optional[str] = None


class LogPackage(CLIModel):
    """A downloaded log package (directory of logs + merged output).

    Represents one download session with all its artifacts.
    """
    name: str  # Directory name (timestamp-based)
    path: str  # Full path to directory
    created: str  # ISO timestamp of when package was created
    file_count: int = 0
    entry_count: int = 0
    has_merged: bool = False
    has_report: bool = False
    is_valid: Optional[bool] = None  # None = not yet validated
    earliest_entry: Optional[str] = None
    latest_entry: Optional[str] = None


class LogPackageDetail(LogPackage):
    """Extended package model with file breakdown and entity stats."""
    files: List[LogFile] = []
    entity_counts: Optional[dict] = None
    level_counts: Optional[dict] = None


class ValidationResult(CLIModel):
    """Result of validating merged output against raw files."""
    is_valid: bool
    total_raw_lines: int = 0
    total_covered_lines: int = 0
    missing_count: int = 0
    missing_lines: List[dict] = []  # [{file, line_number}]


# ==================== Factory Functions ====================


def create_log_entry(data: dict) -> LogEntry:
    """Create a LogEntry model from a parsed dict (e.g., JSONL line)."""
    return LogEntry(**data)


def create_log_package(data: dict) -> LogPackage:
    """Create a LogPackage model from discovery data."""
    return LogPackage(**data)
