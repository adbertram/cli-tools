"""Main entry point for Roomba CLI."""
import typer
from . import __version__
from cli_tools_shared import create_app, run_app, create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

from .client import ClientError
from .config import get_config


def _roomba_login_handler(config, force):
    """Custom login handler for Roomba robot discovery.

    Local TCP handshake only works on older models. J9+ returns UNSUPPORTED_MAGIC
    and requires cloud auth to retrieve local MQTT credentials. Uses dorita980's
    getPasswordCloud.js CLI when local password is unavailable.
    """
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

    # Locate dorita980's getPasswordCloud.js at runtime
    _dorita980_path = None
    try:
        import subprocess
        npm_root_proc = subprocess.run(
            ["npm", "root", "-g"], capture_output=True, text=True, timeout=10
        )
        if npm_root_proc.returncode == 0:
            npm_root = npm_root_proc.stdout.strip()
            candidate = f"{npm_root}/dorita980/bin/getPasswordCloud.js"
            if __import__("os").path.isfile(candidate):
                _dorita980_path = candidate
    except Exception:
        pass

    saved_count = 0
    for robot in robots:
        if not robot.password:
            # J9+ needs cloud auth; older models may need HOME button press
            print_info(f"Local password unavailable for '{robot.name}' at {robot.ip}")
            print_info("Retrieving credentials via iRobot cloud...")

            try:
                import getpass
                import subprocess as sub
                import re as re_mod2

                if not _dorita980_path:
                    print_error("dorita980 not found. Install with:")
                    print_error("  npm install -g dorita980")
                    continue

                # Prompt for iRobot account credentials
                email = input("iRobot account email: ")
                password = getpass.getpass("iRobot account password: ")

                # Run dorita980's getPasswordCloud.js to get local MQTT creds
                proc = sub.run(
                    ["node", _dorita980_path, email, password],
                    capture_output=True, text=True, timeout=30,
                )

                if proc.returncode != 0:
                    print_error(f"Cloud auth failed: {proc.stderr.strip()}")
                    continue

                # Parse dorita980 output lines like "BLID=> XXXX" and "Password=> YYYY <= Yes..."
                blid_match = re_mod2.search(r"BLID=>\s*(.+?)$", proc.stdout, re_mod2.MULTILINE)
                pass_match = re_mod2.search(r"Password=>\s*(.+?)\s*<=", proc.stdout, re_mod2.MULTILINE)

                if blid_match and pass_match:
                    config.add_robot(
                        name=robot.name,
                        ip=robot.ip,
                        blid=blid_match.group(1).strip(),
                        password=pass_match.group(1).strip(),
                        mac=robot.mac,
                        sku=robot.sku,
                        software_ver=robot.software_ver,
                    )
                    print_success(f"Robot '{robot.name}' saved ({robot.ip})")
                    saved_count += 1
                else:
                    print_error("Failed to parse cloud credentials from dorita980 output.")

            except sub.TimeoutExpired:
                print_error("Cloud auth timed out after 30 seconds.")
                continue
            except Exception as e:
                print_error(f"Cloud auth failed: {e}")
                continue

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
from .commands import control
register_commands(app, get_config, control, name="control", help="Control robots (start, stop, dock, etc.)")

from .commands import device
register_commands(app, get_config, device, name="device", help="Manage Roomba device configuration")


@app.command("status")
def status(
    robot: str | None = typer.Argument(None, help="Robot name or IP address (defaults to configured robot)"),
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
        roomba status  # uses default robot
    """
    from .commands.control import control_status

    # Fall back to config default if no robot specified
    config = get_config()
    if robot is None:
        default = config.get_default_robot()
        if default:
            robot = default
        else:
            raise typer.Exit(1)

    control_status(robot=robot, table=table, timeout=timeout)


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
