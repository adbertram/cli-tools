"""Cliclick CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.

Model Architecture:
- CLIModel: Base class with CLI-friendly configuration
- Position: Mouse x,y coordinates
- Color: RGB color values
- Script: Automation script metadata
- ExecutionResult: Command execution outcome
- CliclickStatus: CLI availability and permissions

Usage:
    from .models import Position, Color, Script, CliclickStatus

    # Create from parsed cliclick output
    pos = Position(x=100, y=200)

    # Serialize to JSON
    print_json(pos)
"""
from .base import CLIModel
from .item import (
    # Models
    Position,
    Color,
    Script,
    ExecutionResult,
    CliclickStatus,
    # Factory functions
    create_position,
    create_color,
    create_script,
    create_execution_result,
    create_status,
)

__all__ = [
    # Base
    "CLIModel",
    # Models
    "Position",
    "Color",
    "Script",
    "ExecutionResult",
    "CliclickStatus",
    # Factory functions
    "create_position",
    "create_color",
    "create_script",
    "create_execution_result",
    "create_status",
]
