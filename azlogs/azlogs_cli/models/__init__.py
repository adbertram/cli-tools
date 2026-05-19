"""Azlogs CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.
"""
from .base import CLIModel
from .item import (
    # Enums
    Entity,
    LogLevel,
    ContainerType,
    OutputFormat,
    # Models
    LogEntry,
    LogFile,
    LogPackage,
    LogPackageDetail,
    ValidationResult,
    # Factory functions
    create_log_entry,
    create_log_package,
)

__all__ = [
    # Base
    "CLIModel",
    # Enums
    "Entity",
    "LogLevel",
    "ContainerType",
    "OutputFormat",
    # Models
    "LogEntry",
    "LogFile",
    "LogPackage",
    "LogPackageDetail",
    "ValidationResult",
    # Factory functions
    "create_log_entry",
    "create_log_package",
]
