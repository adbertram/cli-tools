"""Control commands for Roomba CLI."""
import typer
from typing import Optional

from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, print_success, print_error, handle_error

COMMAND_CREDENTIALS = {
    "dock": ["custom"],
    "evac": ["custom"],
    "find": ["custom"],
    "pause": ["custom"],
    "resume": ["custom"],
    "start": ["custom"],
    "status": ["custom"],
    "stop": ["custom"],
}


def _resolve_robot(robot: str | None) -> str:
    """Resolve a robot name, falling back to the configured default."""
    from ..config import get_config
    config = get_config()
    if robot:
        return robot
    default = config.get_default_robot()
    if default:
        return default
    raise ClientError("No robot specified and no default configured")


app = typer.Typer(help="Control Roomba robots")


def _send_command(robot: str, command: str):
    """Helper to send a command and display result.

    Raises typer.Exit(1) on failure, returns silently on success.
    """
    client = get_client()
    result = client.send_command(robot, command)

    print_json(result)

    if not result.success:
        print_error(f"Command failed: {result.message}")
        raise typer.Exit(1)


@app.command("start")
def control_start(
    robot: str | None = typer.Argument(None, help="Robot name or IP address"),
):
    """Start cleaning.

    Examples:
        roomba control start "Living Room"
        roomba control start 192.168.1.50
        roomba control start  # uses default robot
    """
    try:
        _send_command(_resolve_robot(robot), "start")
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("stop")
def control_stop(
    robot: str | None = typer.Argument(None, help="Robot name or IP address"),
):
    """Stop cleaning.

    Examples:
        roomba control stop "Living Room"
        roomba control stop 192.168.1.50
        roomba control stop  # uses default robot
    """
    try:
        _send_command(_resolve_robot(robot), "stop")
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("pause")
def control_pause(
    robot: str | None = typer.Argument(None, help="Robot name or IP address"),
):
    """Pause cleaning.

    Examples:
        roomba control pause "Living Room"
        roomba control pause 192.168.1.50
        roomba control pause  # uses default robot
    """
    try:
        _send_command(_resolve_robot(robot), "pause")
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("resume")
def control_resume(
    robot: str | None = typer.Argument(None, help="Robot name or IP address"),
):
    """Resume cleaning after pause.

    Examples:
        roomba control resume "Living Room"
        roomba control resume 192.168.1.50
        roomba control resume  # uses default robot
    """
    try:
        _send_command(_resolve_robot(robot), "resume")
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("dock")
def control_dock(
    robot: str | None = typer.Argument(None, help="Robot name or IP address"),
):
    """Send robot to dock.

    Examples:
        roomba control dock "Living Room"
        roomba control dock 192.168.1.50
        roomba control dock  # uses default robot
    """
    try:
        _send_command(_resolve_robot(robot), "dock")
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("find")
def control_find(
    robot: str | None = typer.Argument(None, help="Robot name or IP address"),
):
    """Play sound to locate robot.

    Examples:
        roomba control find "Living Room"
        roomba control find 192.168.1.50
        roomba control find  # uses default robot
    """
    try:
        _send_command(_resolve_robot(robot), "find")
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("evac")
def control_evac(
    robot: str | None = typer.Argument(None, help="Robot name or IP address"),
):
    """Empty bin (for models with Clean Base).

    Examples:
        roomba control evac "Living Room"
        roomba control evac 192.168.1.50
        roomba control evac  # uses default robot
    """
    try:
        _send_command(_resolve_robot(robot), "evac")
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("status")
def control_status(
    robot: str | None = typer.Argument(None, help="Robot name or IP address"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    timeout: float = typer.Option(10.0, "--timeout", help="Connection timeout in seconds"),
):
    """Get live status from robot.

    Connects to the robot and retrieves current state including
    battery level, cleaning phase, and bin status.

    Examples:
        roomba control status "Living Room"
        roomba control status "Living Room" --table
        roomba control status "Living Room" --timeout 15
        roomba control status  # uses default robot
    """
    try:
        client = get_client()
        status = client.get_status(_resolve_robot(robot), timeout=timeout)

        if table:
            print_table(
                [status.to_dict()],
                ["name", "battery_percent", "phase", "bin_present", "bin_full"],
                ["Name", "Battery %", "Phase", "Bin Present", "Bin Full"],
            )
        else:
            print_json(status)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(code=handle_error(e))


@app.command("rooms")
def control_rooms(
    robot: str | None = typer.Argument(None, help="Robot name or IP address"),
):
    """Get list of rooms/zones from robot.

    Displays available rooms and favorite zones based on the robot's map data.

    Examples:
        roomba control rooms "Living Room"
        roomba control rooms 192.168.1.50
        roomba control rooms  # uses default robot
    """
    try:
        client = get_client()
        rooms = client.get_rooms(_resolve_robot(robot))

        if not rooms:
            print_error("No rooms found for robot")
            raise typer.Exit(1)

        print_json([room.to_dict() for room in rooms])

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("clean")
def control_clean(
    robot: str | None = typer.Argument(None, help="Robot name or IP address"),
    rooms: Optional[str] = typer.Option(None, "--rooms", "-r", help="Comma-separated room IDs to clean"),
):
    """Start cleaning with optional room selection.

    Start a cleaning mission, optionally limited to specific rooms/zones.

    Examples:
        roomba control clean "Living Room"
        roomba control clean "Living Room" --rooms "room1,room2"
        roomba control clean  # uses default robot, cleans all areas
    """
    try:
        client = get_client()
        resolved_robot = _resolve_robot(robot)

        # Build params dict
        params: Optional[dict] = None
        if rooms:
            room_ids = [rid.strip() for rid in rooms.split(",")]
            params = {"roomIds": room_ids}

        result = client.send_command_with_params(
            resolved_robot, "start", params
        )

        print_json(result)

        if not result.success:
            print_error(f"Clean command failed: {result.message}")
            raise typer.Exit(1)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))
