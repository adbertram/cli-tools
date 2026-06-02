"""Device commands — list, get, health."""
from typing import List, Optional

import typer

from cli_tools_shared.filters import (
    apply_filters,
    apply_limit,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import (
    handle_error,
    print_json,
    print_output,
    print_table,
)

from ..client import get_client
from ..models import DeviceFamily


app = typer.Typer(help="Manage Ring devices (doorbells, cameras, chimes, intercoms)", no_args_is_help=True)


COMMAND_CREDENTIALS = {
    "list": ["username_password"],
    "get": ["username_password"],
    "health": ["username_password"],
}


@app.command("list")
def devices_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of devices"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter results (field:op:value), e.g. family:eq:doorbots"
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
    family: Optional[str] = typer.Option(
        None,
        "--family",
        help=f"Restrict to a single device family ({', '.join(f.value for f in DeviceFamily)})",
    ),
):
    """List all Ring devices on the account.

    Examples:
        ring devices list
        ring devices list --table
        ring devices list --family stickup_cams
        ring devices list --filter "family:eq:doorbots"
    """
    try:
        if filter:
            validate_filters(filter)

        client = get_client()
        devices = client.list_devices()

        if family is not None:
            # Surface invalid values explicitly — no silent skip
            try:
                wanted = DeviceFamily(family)
            except ValueError as exc:
                raise typer.BadParameter(
                    f"Invalid --family '{family}'. Valid values: {', '.join(f.value for f in DeviceFamily)}"
                ) from exc
            devices = [d for d in devices if d.family == wanted]

        if filter:
            devices = apply_filters(devices, filter)
        devices = apply_limit(devices, limit)
        if properties:
            devices = apply_properties_filter(devices, properties)

        if table:
            columns = (
                [c.strip() for c in properties.split(",")]
                if properties
                else ["id", "name", "family", "kind", "model"]
            )
            print_table(devices, columns, columns)
        else:
            print_json(devices)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def devices_get(
    identifier: str = typer.Argument(..., help="Device name or numeric ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """Get full details (including health) for a single device."""
    try:
        client = get_client()
        device = client.get_device(identifier)

        if properties:
            shown = apply_properties_filter([device], properties)[0]
        else:
            shown = device

        if table:
            data = shown.model_dump() if hasattr(shown, "model_dump") else dict(shown)
            rows = [{"field": k, "value": str(v)} for k, v in data.items() if v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(shown)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("health")
def devices_health(
    identifier: str = typer.Argument(..., help="Device name or numeric ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Show battery, wifi, and connection status for a device."""
    try:
        client = get_client()
        health = client.get_device_health(identifier)
        print_output(health, table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
