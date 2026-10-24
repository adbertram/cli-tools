"""Device management commands for Roomba CLI.

Handles all robot configuration: list, get, add (manual), discover (passive scan).
"""
import typer
from typing import Optional

from pydantic import BaseModel
COMMAND_CREDENTIALS = {
    "add": ["custom"],
    "get": ["custom"],
    "list": ["custom"],
    "discover": [],  # Passive scan, no credentials needed
}

from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, print_info, handle_error


app = typer.Typer(help="Manage Roomba device configuration")


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


def model_to_dict(item):
    """Convert model or dict to dict for field extraction."""
    if isinstance(item, BaseModel):
        return item.model_dump(mode="json")
    return item


def extract_field(item, field: str):
    """Extract a field value, supporting dot-notation for nested fields."""
    data = model_to_dict(item)
    parts = field.split(".")
    value = data
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def extract_fields(items: list, fields: list) -> list:
    """Extract specified fields from items, supporting dot-notation."""
    result = []
    for item in items:
        extracted = {}
        for field in fields:
            value = extract_field(item, field)
            extracted[field] = value
        result.append(extracted)
    return result


@app.command("list")
def device_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of devices to return"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """List configured Roomba devices.

    Examples:
        roomba device list
        roomba device list --table
        roomba device list --properties "name,ip,blid"
    """
    try:
        client = get_client()
        robots = client.list_robots(limit=limit)

        if not robots:
            print_info("No robots configured.")
            print_json([])
            return

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            robots = extract_fields(robots, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(robots, fields, fields)
            else:
                print_table(robots, ["name", "ip", "blid"], ["Name", "IP", "BLID"])
        else:
            print_json(robots)

    except ClientError as e:
        print_info(str(e))
        print_json([])
    except Exception as e:
        raise typer.Exit(code=handle_error(e))


@app.command("get")
def device_get(
    robot: str | None = typer.Argument(None, help="Device name or IP address (defaults to configured robot)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """Get details for a specific Roomba device.

    Examples:
        roomba device get "Living Room"
        roomba device get 192.168.1.50
        roomba device get  # uses default robot
    """
    try:
        client = get_client()
        robot_detail = client.get_robot(_resolve_robot(robot))

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            robot_detail = extract_fields([robot_detail], fields)[0]

        if table:
            item_dict = model_to_dict(robot_detail)
            rows = [{"field": k, "value": str(v)} for k, v in item_dict.items() if v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(robot_detail)

    except ClientError as e:
        print_info(str(e))
        raise typer.Exit(code=handle_error(e))
    except Exception as e:
        raise typer.Exit(code=handle_error(e))


@app.command("add")
def device_add(
    name: str = typer.Argument(..., help="Device name (e.g., 'Living Room Roomba')"),
    ip: str = typer.Argument(..., help="Device IP address on the network"),
    blid: Optional[str] = typer.Option(None, "--blid", "-b", help="Device BLID identifier"),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Device local password"),
):
    """Add a Roomba device to the CLI configuration without network discovery.

    Examples:
        roomba device add "Kitchen" 192.168.1.50
        roomba device add "Kitchen" 192.168.1.50 --blid 1234567 --password abcdef
        roomba device add Robo 10.0.0.5 -b 999999 -p secret123
    """
    from ..config import get_config
    from cli_tools_shared.output import print_info, print_success, print_error

    config = get_config()

    if not blid or not password:
        print_info(f"Device '{name}' at {ip} detected — BLID and password required.")
        print_info("Enter credentials to save this device:")
        if not blid:
            blid = typer.prompt("BLID (device ID)", default="")
        if not password:
            password = typer.prompt("Password", default="", hide_input=True)

    if not blid or not password:
        print_error("Both BLID and password are required. Device not saved.")
        raise typer.Exit(code=1)

    config.add_robot(name=name, ip=ip, blid=blid, password=password)
    print_success(f"Device '{name}' added ({ip})")


@app.command("discover")
def device_discover():
    """Scan the local network for Roomba devices (passive, no credentials).

    Discovers all visible robots without attempting password retrieval.
    Shows which ones are already configured and flags unconfigured ones.

    Examples:
        roomba device discover
    """
    from ..client import get_client, ClientError
    from cli_tools_shared.output import print_info, print_success, handle_error

    try:
        client = get_client()
        robots = client.discover_robots()

        if not robots:
            print_info("No Roomba devices found on the network.")
            return

        config = client.config
        configured_names = set(config.robots.keys())

        for robot in robots:
            status = "configured" if robot.name in configured_names else "not configured"
            blid_str = f"BLID: {robot.blid}" if robot.blid else "BLID: unknown"
            print_info(f"{robot.name} ({status}) — {robot.ip} — {blid_str}")

        print_success(f"Found {len(robots)} Roomba device(s) on the network.")

    except ClientError as e:
        print_info(str(e))
        raise typer.Exit(code=handle_error(e))
    except Exception as e:
        raise typer.Exit(code=handle_error(e))
