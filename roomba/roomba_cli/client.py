"""Roomba client using roombapy library.

Provides methods to discover, connect, and control Roomba vacuums.
"""
import time
import threading
from typing import List, Optional

from roombapy import RoombaDiscovery, RoombaFactory, RoombaPassword, RoombaInfo
from roombapy.roomba import Roomba, RoombaConnectionError
from roombapy.const import ROOMBA_ERROR_MESSAGES

from .config import get_config
from .models import (
    RobotInfo,
    RobotStatus,
    RobotDetail,
    CommandResult,
    CleaningPhase,
)


class ClientError(Exception):
    """Custom exception for Roomba client errors."""

    pass


class RoombaClient:
    """Client for interacting with Roomba vacuums via roombapy library."""

    def __init__(self):
        """Initialize Roomba client."""
        self.config = get_config()

    def discover_robots(self, ip: Optional[str] = None) -> List[RobotInfo]:
        """Discover Roomba robots on the local network.

        Args:
            ip: Optional specific IP address to check

        Returns:
            List of discovered RobotInfo models
        """
        discovery = RoombaDiscovery()
        discovered: List[RoombaInfo] = []

        if ip:
            bot = discovery.get(ip)
            if bot:
                discovered = [bot]
        else:
            discovered = list(discovery.get_all())

        robots = []
        for bot in discovered:
            # Try to get password
            password = None
            try:
                password = RoombaPassword(bot.ip).get_password()
            except Exception:
                pass

            robots.append(
                RobotInfo(
                    ip=bot.ip,
                    blid=bot.blid,
                    name=bot.robot_name or f"Roomba-{bot.blid[:8]}",
                    mac=bot.mac,
                    password=password,
                    sku=getattr(bot, "sku", None),
                    software_ver=getattr(bot, "sw", None),
                    hostname=getattr(bot, "hostname", None),
                )
            )

        return robots

    def list_robots(self, limit: int = 100) -> List[RobotInfo]:
        """List configured robots from config file.

        Args:
            limit: Maximum number of robots to return

        Returns:
            List of RobotInfo models from config
        """
        robots = []
        for name, robot_data in self.config.robots.items():
            robots.append(
                RobotInfo(
                    ip=robot_data.get("ip", ""),
                    blid=robot_data.get("blid", ""),
                    name=name,
                    mac=robot_data.get("mac"),
                    password="***" if robot_data.get("password") else None,
                    sku=robot_data.get("sku"),
                    software_ver=robot_data.get("software_ver"),
                )
            )

        return robots[:limit]

    def get_robot(self, name_or_ip: str) -> RobotDetail:
        """Get detailed information about a robot.

        Args:
            name_or_ip: Robot name or IP address

        Returns:
            RobotDetail model with full information
        """
        robot_config = self.config.get_robot(name_or_ip)
        if not robot_config:
            raise ClientError(f"Robot '{name_or_ip}' not found in configuration")

        return RobotDetail(
            ip=robot_config["ip"],
            blid=robot_config["blid"],
            name=robot_config["name"],
            mac=robot_config.get("mac"),
            sku=robot_config.get("sku"),
            software_ver=robot_config.get("software_ver"),
            connected=False,
        )

    def get_status(self, name_or_ip: str, timeout: float = 10.0) -> RobotStatus:
        """Get live status from a robot.

        Connects to the robot, waits for state data, then disconnects.

        Args:
            name_or_ip: Robot name or IP address
            timeout: Maximum time to wait for state data

        Returns:
            RobotStatus model with live data
        """
        robot_config = self.config.get_robot(name_or_ip)
        if not robot_config:
            raise ClientError(f"Robot '{name_or_ip}' not found in configuration")

        ip = robot_config["ip"]
        blid = robot_config["blid"]
        password = robot_config.get("password")

        if not password:
            raise ClientError(f"No password stored for robot '{name_or_ip}'")

        # Create roomba instance
        roomba = RoombaFactory.create_roomba(ip, blid, password)

        # Event to signal when we have data
        data_received = threading.Event()
        status_data = {}

        def on_message(message):
            nonlocal status_data
            # Extract status from message
            if "state" in message and "reported" in message["state"]:
                reported = message["state"]["reported"]
                if "batPct" in reported or "cleanMissionStatus" in reported:
                    status_data.update(reported)
                    data_received.set()

        roomba.register_on_message_callback(on_message)

        try:
            # Small delay before connecting (roombapy recommendation)
            time.sleep(0.5)
            roomba.connect()

            # Wait for data
            data_received.wait(timeout=timeout)

            # Extract status
            phase_str = "unknown"
            error_code = None
            error_message = None

            if "cleanMissionStatus" in status_data:
                cms = status_data["cleanMissionStatus"]
                phase_str = cms.get("phase", "unknown")
                error_code = cms.get("error")
                if error_code and error_code in ROOMBA_ERROR_MESSAGES:
                    error_message = ROOMBA_ERROR_MESSAGES[error_code]

            bin_data = status_data.get("bin", {})

            return RobotStatus(
                name=robot_config["name"],
                ip=ip,
                battery_percent=status_data.get("batPct", 0),
                phase=CleaningPhase(phase_str),
                bin_present=bin_data.get("present", True),
                bin_full=bin_data.get("full", False),
                error_code=error_code,
                error_message=error_message,
            )

        except RoombaConnectionError as e:
            raise ClientError(f"Failed to connect to robot: {e}")
        finally:
            try:
                roomba.disconnect()
            except Exception:
                pass

    def send_command(
        self, name_or_ip: str, command: str, params: Optional[dict] = None
    ) -> CommandResult:
        """Send a command to a robot.

        Args:
            name_or_ip: Robot name or IP address
            command: Command to send (start, stop, pause, resume, dock, find, evac)
            params: Optional command parameters

        Returns:
            CommandResult model
        """
        robot_config = self.config.get_robot(name_or_ip)
        if not robot_config:
            raise ClientError(f"Robot '{name_or_ip}' not found in configuration")

        ip = robot_config["ip"]
        blid = robot_config["blid"]
        password = robot_config.get("password")

        if not password:
            raise ClientError(f"No password stored for robot '{name_or_ip}'")

        # Validate command
        valid_commands = ["start", "stop", "pause", "resume", "dock", "find", "evac"]
        if command not in valid_commands:
            raise ClientError(
                f"Invalid command '{command}'. Valid commands: {', '.join(valid_commands)}"
            )

        # Create roomba instance
        roomba = RoombaFactory.create_roomba(ip, blid, password)

        try:
            # Small delay before connecting
            time.sleep(0.5)
            roomba.connect()

            # Wait briefly for connection to establish
            time.sleep(1.0)

            # Send the command
            roomba.send_command(command, params or {})

            # Wait briefly for command to be sent
            time.sleep(0.5)

            return CommandResult(
                success=True,
                robot=robot_config["name"],
                command=command,
                message=f"Command '{command}' sent successfully",
            )

        except RoombaConnectionError as e:
            return CommandResult(
                success=False,
                robot=robot_config["name"],
                command=command,
                message=f"Connection failed: {e}",
            )
        except Exception as e:
            return CommandResult(
                success=False,
                robot=robot_config["name"],
                command=command,
                message=f"Command failed: {e}",
            )
        finally:
            try:
                roomba.disconnect()
            except Exception:
                pass


# Module-level client instance - singleton pattern
_client: Optional[RoombaClient] = None


def get_client() -> RoombaClient:
    """Get or create the global Roomba client instance."""
    global _client
    if _client is None:
        _client = RoombaClient()
    return _client
