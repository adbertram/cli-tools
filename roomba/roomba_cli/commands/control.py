"""Control commands for Roomba CLI."""
import typer
from typing import Optional

from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, print_success, print_error, handle_error

COMMAND_CREDENTIALS = {
    "dock": [
        "custom"
    ],
    "evac": [
        "custom"
    ],
    "find": [
        "custom"
    ],
    "pause": [
        "custom"
    ],
    "resume": [
        "custom"
    ],
    "start": [
        "custom"
    ],
    "status": [
        "custom"
    ],
    "stop": [
        "custom"
    ]
}


app = typer.Typer(help="Control Roomba robots")


def _send_command(robot: str, command: str, table: bool = False):
    """Helper to send a command and display result."""
    client = get_client()
    result = client.send_command(robot, command)

    if table:
        print_table(
            [result.to_dict()],
            ["robot", "command", "success", "message"],
            ["Robot", "Command", "Success", "Message"],
        )
    else:
        print_json(result)

    if not result.success:
        raise typer.Exit(1)


@app.command("start")
def control_start(
    robot: str = typer.Argument(..., help="Robot name or IP address"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Start cleaning.

    Examples:
        roomba control start "Living Room"
        roomba control start 192.168.1.50
    """
    try:
        _send_command(robot, "start", table)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("stop")
def control_stop(
    robot: str = typer.Argument(..., help="Robot name or IP address"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Stop cleaning.

    Examples:
        roomba control stop "Living Room"
    """
    try:
        _send_command(robot, "stop", table)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("pause")
def control_pause(
    robot: str = typer.Argument(..., help="Robot name or IP address"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Pause cleaning.

    Examples:
        roomba control pause "Living Room"
    """
    try:
        _send_command(robot, "pause", table)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("resume")
def control_resume(
    robot: str = typer.Argument(..., help="Robot name or IP address"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Resume cleaning after pause.

    Examples:
        roomba control resume "Living Room"
    """
    try:
        _send_command(robot, "resume", table)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("dock")
def control_dock(
    robot: str = typer.Argument(..., help="Robot name or IP address"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Send robot to dock.

    Examples:
        roomba control dock "Living Room"
    """
    try:
        _send_command(robot, "dock", table)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("find")
def control_find(
    robot: str = typer.Argument(..., help="Robot name or IP address"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Play sound to locate robot.

    Examples:
        roomba control find "Living Room"
    """
    try:
        _send_command(robot, "find", table)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("evac")
def control_evac(
    robot: str = typer.Argument(..., help="Robot name or IP address"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Empty bin (for models with Clean Base).

    Examples:
        roomba control evac "Living Room"
    """
    try:
        _send_command(robot, "evac", table)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("status")
def control_status(
    robot: str = typer.Argument(..., help="Robot name or IP address"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    timeout: float = typer.Option(10.0, "--timeout", help="Connection timeout in seconds"),
):
    """
    Get live status from robot.

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
        raise typer.Exit(handle_error(e))
