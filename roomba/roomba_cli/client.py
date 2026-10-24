"""Roomba client using the synchronous roombapy 1.9 API.

Provides methods to discover, connect, and control Roomba vacuums.
The dependency is constrained to the supported synchronous API.
"""
import time
import threading
from typing import List, Optional, Any, Dict

from roombapy import RoombaDiscovery, RoombaPassword, RoombaInfo, RoombaFactory
from roombapy.roomba import (
    RoombaConnectionError,
)
from roombapy.const import ROOMBA_ERROR_MESSAGES

from .config import get_config
from .models import (
    RobotInfo,
    RobotStatus,
    RobotDetail,
    CommandResult,
    CleaningPhase,
    RoomInfo,
)


class ClientError(Exception):
    """Custom exception for Roomba client errors."""

    pass


class RoombaClient:
    """Client for interacting with Roomba vacuums via roombapy 1.9."""

    def __init__(self):
        """Initialize Roomba client."""
        self.config = get_config()

    def discover_robots(self, ip=None):
        """Discover Roomba robots on the local network.

        Args:
            ip: Optional specific IP address to check

        Returns:
            List of discovered RobotInfo models
        """
        discovery = RoombaDiscovery()
        if ip:
            bot = discovery.get(ip)
            bots = [bot] if bot else []
        else:
            bots = list(discovery.get_all())

        robots = []
        for bot in bots:
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

    def list_robots(self, limit=100):
        """List configured robots from config file."""
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

    def get_robot(self, name_or_ip):
        """Get detailed information about a robot."""
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

    def _make_roomba(self, ip, blid, password):
        """Create a synchronous client with its public factory."""
        return RoombaFactory.create_roomba(ip, blid, password)

    def get_status(self, name_or_ip, timeout=10.0):
        """Get live status from a robot."""
        robot_config = self.config.get_robot(name_or_ip)
        if not robot_config:
            raise ClientError(f"Robot '{name_or_ip}' not found in configuration")

        ip = robot_config["ip"]
        status_data = self._get_state_reported(name_or_ip, timeout=timeout)
        cms = status_data.get("cleanMissionStatus", {})
        error_code = cms.get("error")
        bin_data = status_data.get("bin", {})
        return RobotStatus(
            name=robot_config["name"],
            ip=ip,
            battery_percent=status_data.get("batPct"),
            phase=CleaningPhase(cms.get("phase", "unknown")),
            bin_present=bin_data.get("present"),
            bin_full=bin_data.get("full"),
            error_code=error_code,
            error_message=ROOMBA_ERROR_MESSAGES.get(error_code),
        )

    def send_command(self, name_or_ip, command, params=None):
        """Send a command to a robot."""
        robot_config = self.config.get_robot(name_or_ip)
        if not robot_config:
            raise ClientError(f"Robot '{name_or_ip}' not found in configuration")

        ip = robot_config["ip"]
        blid = robot_config["blid"]
        password = robot_config.get("password")
        if not password:
            raise ClientError(f"No password stored for robot '{name_or_ip}'")

        valid_commands = ["start", "stop", "pause", "resume", "dock", "find", "evac"]
        if command not in valid_commands:
            raise ClientError(
                f"Invalid command '{command}'. Valid commands: {', '.join(valid_commands)}"
            )

        roomba = self._make_roomba(ip, blid, password)

        try:
            time.sleep(0.5)
            roomba.connect()
            time.sleep(1.0)
            roomba.send_command(command, params or {})
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

    def _get_state_reported(self, name_or_ip, timeout=15.0):
        """Internal: connect to robot and return reported state data."""
        robot_config = self.config.get_robot(name_or_ip)
        if not robot_config:
            raise ClientError(f"Robot '{name_or_ip}' not found in configuration")

        ip = robot_config["ip"]
        blid = robot_config["blid"]
        password = robot_config.get("password")
        if not password:
            raise ClientError(f"No password stored for robot '{name_or_ip}'")

        roomba = self._make_roomba(ip, blid, password)

        reported_data = {}
        data_received = threading.Event()

        def on_message(message):
            nonlocal reported_data
            if "state" in message and "reported" in message["state"]:
                reported = message["state"]["reported"]
                reported_data.update(reported)
                if "batPct" in reported or "cleanMissionStatus" in reported:
                    data_received.set()

        roomba.register_on_message_callback(on_message)

        try:
            time.sleep(0.5)
            roomba.connect()
            if not data_received.wait(timeout=timeout):
                if roomba.client_error:
                    raise ClientError("Robot MQTT connection rejected")
                if not roomba.roomba_connected:
                    raise ClientError("Robot MQTT connection not established before timeout")
                raise ClientError("No reported telemetry received before timeout")
            return dict(reported_data)
        except RoombaConnectionError as e:
            raise ClientError("Failed to connect to robot") from e
        finally:
            try:
                roomba.disconnect()
            except Exception:
                pass

    def start_cleaning(self, name_or_ip):
        """Dispatch start with the existing pmaps-derived parameters.

        This legacy map interpretation has not been verified against app room
        selection. Dispatch does not confirm robot execution.
        """
        robot_config = self.config.get_robot(name_or_ip)
        if not robot_config:
            raise ClientError(f"Robot '{name_or_ip}' not found in configuration")

        ip = robot_config["ip"]
        blid = robot_config["blid"]
        password = robot_config.get("password")
        if not password:
            raise ClientError(f"No password stored for robot '{name_or_ip}'")

        # Fetch state to get pmap data
        reported_data = {}
        try:
            reported_data = self._get_state_reported(name_or_ip, timeout=15.0)
        except Exception as e:
            return CommandResult(
                success=False,
                robot=robot_config["name"],
                command="start_cleaning",
                message=f"Failed to get robot state: {e}",
            )

        # Extract map/region info from pmaps if available
        params = {}
        pmaps = reported_data.get("pmaps")
        if isinstance(pmaps, list) and len(pmaps) > 0:
            region_ids = []
            for item in pmaps:
                if isinstance(item, dict):
                    rid = item.get("id") or item.get("region_id", "")
                    if rid:
                        region_ids.append(rid)
            if region_ids:
                params["regions"] = [{"rid": rid} for rid in region_ids]

        # Dispatch the legacy parameters; robot execution is not confirmed.
        roomba = self._make_roomba(ip, blid, password)
        try:
            time.sleep(0.5)
            roomba.connect()
            time.sleep(1.0)
            roomba.send_command("start", params if params else None)

            has_regions = bool(params.get("regions"))
            msg = "Start command sent with map context" if has_regions else "Start command sent"
            return CommandResult(
                success=True,
                robot=robot_config["name"],
                command="start_cleaning",
                message=msg,
            )
        except RoombaConnectionError as e:
            return CommandResult(
                success=False,
                robot=robot_config["name"],
                command="start_cleaning",
                message=f"Connection failed: {e}",
            )
        except Exception as e:
            return CommandResult(
                success=False,
                robot=robot_config["name"],
                command="start_cleaning",
                message=f"Command failed: {e}",
            )
        finally:
            try:
                roomba.disconnect()
            except Exception:
                pass

    def get_rooms(self, name_or_ip):
        """Get list of rooms from robot's pmaps data."""
        reported_data = self._get_state_reported(name_or_ip, timeout=15.0)
        rooms_data = reported_data.get("pmaps", [])
        rooms = []
        if isinstance(rooms_data, list):
            for item in rooms_data:
                if isinstance(item, dict):
                    room_id = str(item.get("id", ""))
                    name = item.get("name", f"Room {room_id}")
                    is_fav = item.get("favoriteZone", False)
                    rooms.append(RoomInfo(room_id, name, is_fav))
        return rooms

    def get_state_reported(self, name_or_ip):
        """Get the full reported state from a robot."""
        return self._get_state_reported(name_or_ip, timeout=15.0)


_client = None


def get_client():
    """Get or create the global Roomba client instance."""
    global _client
    if _client is None:
        _client = RoombaClient()
    return _client
