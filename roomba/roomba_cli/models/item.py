"""Roomba models for CLI.

Models for representing Roomba robots, their status, and command results.
"""
from enum import Enum
from typing import Optional

from pydantic import Field

from .base import CLIModel


# ==================== Enums ====================


class CleaningPhase(str, Enum):
    """Roomba cleaning phase states."""

    CHARGE = "charge"
    RUN = "run"
    STOP = "stop"
    PAUSE = "pause"
    STUCK = "stuck"
    HMPOSTMSN = "hmPostMsn"  # Heading home post-mission
    HMMIDMSN = "hmMidMsn"  # Heading home mid-mission (recharge)
    HMUSRDOCK = "hmUsrDock"  # User requested dock
    EVAC = "evac"  # Evacuating bin
    UNKNOWN = "unknown"

    @classmethod
    def _missing_(cls, value):
        """Handle unknown phase values gracefully."""
        return cls.UNKNOWN


# ==================== Models ====================


class BinStatus(CLIModel):
    """Roomba bin status."""

    present: bool = True
    full: bool = False


class RobotInfo(CLIModel):
    """Robot information from discovery or config.

    Used for list commands - basic robot info.
    """

    # Required fields
    ip: str
    blid: str
    name: str

    # Optional fields
    mac: Optional[str] = None
    password: Optional[str] = None
    sku: Optional[str] = None
    software_ver: Optional[str] = None
    hostname: Optional[str] = None


class RobotStatus(CLIModel):
    """Live robot status from connected Roomba.

    Used for status command - includes live state data.
    """

    # Required fields
    name: str
    ip: str

    # Status fields
    battery_percent: int = 0
    phase: CleaningPhase = CleaningPhase.UNKNOWN
    bin_present: bool = True
    bin_full: bool = False

    # Optional detail fields
    error_code: Optional[int] = None
    error_message: Optional[str] = None
    mission_id: Optional[str] = None
    position_x: Optional[int] = None
    position_y: Optional[int] = None


class RobotDetail(CLIModel):
    """Detailed robot information.

    Used for get command - full details including config.
    """

    # Required fields
    ip: str
    blid: str
    name: str

    # Discovery info
    mac: Optional[str] = None
    sku: Optional[str] = None
    software_ver: Optional[str] = None
    hostname: Optional[str] = None

    # Live status (when connected)
    connected: bool = False
    battery_percent: Optional[int] = None
    phase: Optional[CleaningPhase] = None
    bin_present: Optional[bool] = None
    bin_full: Optional[bool] = None


class CommandResult(CLIModel):
    """Result of a command sent to a robot."""

    success: bool
    robot: str
    command: str
    message: Optional[str] = None


class AuthStatus(CLIModel):
    """Authentication/configuration status."""

    authenticated: bool
    robots_configured: int = 0
    config_path: Optional[str] = None
    message: Optional[str] = None


# ==================== Factory Functions ====================


def create_robot_info(data: dict) -> RobotInfo:
    """Create a RobotInfo model from discovery data.

    Args:
        data: Raw dict from discovery

    Returns:
        RobotInfo model instance
    """
    return RobotInfo(**data)


def create_robot_status(data: dict) -> RobotStatus:
    """Create a RobotStatus model from state data.

    Args:
        data: Raw dict from roomba master_state

    Returns:
        RobotStatus model instance
    """
    return RobotStatus(**data)
