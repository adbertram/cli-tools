"""Main entry point for Roomba CLI."""
import typer
from . import __version__
from cli_tools_shared import create_app, run_app, create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

from .client import ClientError
from .config import get_config


def _roomba_login_handler(config, force):
    """Custom login handler for Roomba robot discovery."""
    from .client import get_client
    from cli_tools_shared.output import print_info, print_success, print_error

    if force:
        config.clear_ephemeral()

    print_info("Discovering Roomba robots on the network...")
    client = get_client()
    robots = client.discover_robots()

    if not robots:
        print_error("No robots found on the network")
        print_info("Tips:")
        print_info("  - Ensure your Roomba is on and connected to WiFi")
        print_info("  - Make sure you're on the same network as the Roomba")
        print_info("  - Try specifying the IP in robot config manually")
        return

    saved_count = 0
    for robot in robots:
        if not robot.password:
            print_info(f"Could not obtain password for '{robot.name}' at {robot.ip}")
            print_info("  Try pressing and holding HOME button on robot for 2 seconds")
            continue

        config.add_robot(
            name=robot.name,
            ip=robot.ip,
            blid=robot.blid,
            password=robot.password,
            mac=robot.mac,
            sku=robot.sku,
            software_ver=robot.software_ver,
        )
        print_success(f"Robot '{robot.name}' saved ({robot.ip})")
        saved_count += 1

    if saved_count == 0:
        print_info("No new robots were saved")
    else:
        print_success(f"Saved {saved_count} robot(s)")


def _roomba_test_handler(config):
    """Test handler for Roomba CLI."""
    return config.test_connection()


app = create_app(
    name="roomba",
    help="CLI to control iRobot Roomba vacuums",
    version=__version__,
)

# Register auth commands from cli_tools_shared
auth_app = create_auth_app(
    get_config,
    tool_name="roomba",
    login_handler=_roomba_login_handler,
    test_handler=_roomba_test_handler,
)
app.add_typer(auth_app, name="auth", help="Manage robot authentication and discovery")
app.add_typer(create_cache_app(get_config), name="cache", help="Manage CLI cache")


# Register command modules
from .commands import robots, control

register_commands(app, get_config, robots, name="robots", help="List and view robot information")
register_commands(app, get_config, control, name="control", help="Control robots (start, stop, dock, etc.)")
# Top-level status command for convenience
@app.command("status")
def status(
    robot: str = typer.Argument(..., help="Robot name or IP address"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    timeout: float = typer.Option(
        10.0, "--timeout", help="Connection timeout in seconds"
    ),
):
    """
    Get live status from a robot (shortcut for 'control status').

    Examples:
        roomba status "Living Room"
        roomba status "Living Room" --table
    """
    from .commands.control import control_status

    control_status(robot=robot, table=table, timeout=timeout)


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
