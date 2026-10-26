"""Control commands for Roomba CLI."""
import typer
from cli_tools_shared.output import command
from typing import Optional

from .client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, print_success, print_error, handle_error


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
@command
def control_start(
    robot: str = typer.Argument(..., help="Robot name or IP address"),
):
    """Start cleaning.

    Examples:
        roomba control start "Living Room"
        roomba control start 192.168.1.50
    """
    _send_command(robot, "start")


@app.command("stop")
@command
def control_stop(
    robot: str = typer.Argument(..., help="Robot name or IP address"),
):
    """Stop cleaning.

    Examples:
        roomba control stop "Living Room"
    """
    _send_command(robot, "stop")


@app.command("pause")
@command
def control_pause(
    robot: str = typer.Argument(..., help="Robot name or IP address"),
):
    """Pause cleaning.

    Examples:
        roomba control pause "Living Room"
    """
    _send_command(robot, "pause")


@app.command("resume")
@command
def control_resume(
    robot: str = typer.Argument(..., help="Robot name or IP address"),
):
    """Resume cleaning after pause.

    Examples:
        roomba control resume "Living Room"
    """
    _send_command(robot, "resume")


@app.command("dock")
@command
def control_dock(
    robot: str = typer.Argument(..., help="Robot name or IP address"),
):
    """Send robot to dock.

    Examples:
        roomba control dock "Living Room"
    """
    _send_command(robot, "dock")


@app.command("find")
@command
def control_find(
    robot: str = typer.Argument(..., help="Robot name or IP address"),
):
    """Play sound to locate robot.

    Examples:
        roomba control find "Living Room"
    """
    _send_command(robot, "find")


@app.command("evac")
@command
def control_evac(
    robot: str = typer.Argument(..., help="Robot name or IP address"),
):
    """Empty bin (for models with Clean Base).

    Examples:
        roomba control evac "Living Room"
    """
    _send_command(robot, "evac")


@app.command("status")
@command
def control_status(
    robot: str = typer.Argument(..., help="Robot name or IP address"),
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
    """
    try:
        client = get_client()
        status = client.get_status(robot, timeout=timeout)

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
