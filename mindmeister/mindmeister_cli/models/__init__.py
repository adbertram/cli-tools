"""MindMeister CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.

Model Architecture:
- CLIModel: Base class with CLI-friendly configuration
- Map: Basic map metadata for list commands
- MapDetail: Full map with ideas for get commands
- Idea: Individual node within a map
- ExportUrls: Export URLs for different formats
"""
from .base import CLIModel
from .item import (
    # Models
    Map,
    MapDetail,
    Idea,
    ExportUrls,
    # Factory functions
    create_map,
    create_map_detail,
    create_export_urls,
)

__all__ = [
    # Base
    "CLIModel",
    # Models
    "Map",
    "MapDetail",
    "Idea",
    "ExportUrls",
    # Factory functions
    "create_map",
    "create_map_detail",
    "create_export_urls",
]
