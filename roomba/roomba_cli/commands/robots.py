"""Robot management commands for Roomba CLI."""
import typer
from typing import Optional, List

from pydantic import BaseModel
COMMAND_CREDENTIALS = {
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ]
}

from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, print_info, handle_error
from cli_tools_shared.filters import apply_filters
from cli_tools_shared import FilterMap


app = typer.Typer(help="Manage Roomba robots")


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
def robots_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(
        100, "--limit", "-l", help="Maximum number of robots to return"
    ),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to display"
    ),
    discover: bool = typer.Option(
        False, "--discover", "-d", help="Discover robots on network instead of listing configured"
    ),
):
    """
    List configured or discovered Roomba robots.

    Examples:
        roomba robots list                   # List configured robots
        roomba robots list --table           # Display as table
        roomba robots list --discover        # Discover robots on network
        roomba robots list --properties "name,ip,blid"
    """
    try:
        client = get_client()

        if discover:
            print_info("Discovering robots on the network...")
            robots = client.discover_robots()
        else:
            robots = client.list_robots(limit=limit)

        # Apply client-side filtering
        if filter and robots:
            robot_dicts = [model_to_dict(r) if isinstance(r, BaseModel) else r for r in robots]
            robot_dicts = apply_filters(robot_dicts, list(filter))
            robots = robot_dicts

        if not robots:
            if discover:
                print_info("No robots found on the network")
            else:
                print_info("No robots configured. Run 'roomba auth login' to discover.")
            print_json([])
            return

        # Apply property selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            robots = extract_fields(robots, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(robots, fields, fields)
            else:
                print_table(
                    robots,
                    ["name", "ip", "blid"],
                    ["Name", "IP", "BLID"],
                )
        else:
            print_json(robots)

    except ClientError as e:
        print_info(str(e))
        print_json([])
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def robots_get(
    robot: str = typer.Argument(..., help="Robot name or IP address"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to display"
    ),
):
    """
    Get details for a specific robot.

    Examples:
        roomba robots get "Living Room"
        roomba robots get 192.168.1.50
        roomba robots get "Living Room" --table
        roomba robots get "Living Room" --properties "name,ip,blid"
    """
    try:
        client = get_client()
        robot_detail = client.get_robot(robot)

        # Apply property selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            robot_detail = extract_fields([robot_detail], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([robot_detail], fields, fields)
            else:
                # Convert model to key-value table
                item_dict = model_to_dict(robot_detail)
                rows = [
                    {"field": k, "value": str(v)}
                    for k, v in item_dict.items()
                    if v is not None
                ]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(robot_detail)

    except Exception as e:
        raise typer.Exit(handle_error(e))
