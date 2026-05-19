"""Roomba CLI models.

All models inherit from CLIModel which provides consistent JSON serialization.
"""
from .base import CLIModel
from .item import (
    # Enums
    CleaningPhase,
    # Models
    BinStatus,
    RobotInfo,
    RobotStatus,
    RobotDetail,
    CommandResult,
    AuthStatus,
    # Factory functions
    create_robot_info,
    create_robot_status,
)

__all__ = [
    # Base
    "CLIModel",
    # Enums
    "CleaningPhase",
    # Models
    "BinStatus",
    "RobotInfo",
    "RobotStatus",
    "RobotDetail",
    "CommandResult",
    "AuthStatus",
    # Factory functions
    "create_robot_info",
    "create_robot_status",
]
