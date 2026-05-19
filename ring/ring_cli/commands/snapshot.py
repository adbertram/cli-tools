"""Snapshot commands — list snapshot-capable devices and capture fresh JPEGs."""
from pathlib import Path
from typing import List, Optional

import typer

from cli_tools_shared.filters import (
    apply_filters,
    apply_limit,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import handle_error, print_json, print_output, print_table

from ..client import get_client
from ..models import DeviceFamily


app = typer.Typer(help="Capture device snapshots", no_args_is_help=True)


COMMAND_CREDENTIALS = {
    "list": ["username_password"],
    "get": ["username_password"],
}


@app.command("list")
def snapshot_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of devices"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter results (field:op:value)"
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """List devices that support snapshot capture (doorbells and cameras)."""
    try:
        if filter:
            validate_filters(filter)
        client = get_client()
        devices = [
            d for d in client.list_devices()
            if d.family in (DeviceFamily.DOORBOTS, DeviceFamily.AUTHORIZED_DOORBOTS, DeviceFamily.STICKUP_CAMS)
        ]
        if filter:
            devices = apply_filters(devices, filter)
        devices = apply_limit(devices, limit)
        if properties:
            devices = apply_properties_filter(devices, properties)

        if table:
            columns = (
                [c.strip() for c in properties.split(",")]
                if properties
                else ["id", "name", "family", "kind"]
            )
            print_table(devices, columns, columns)
        else:
            print_json(devices)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def snapshot_get(
    device: str = typer.Option(..., "--device", "-d", help="Device name or numeric ID"),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output path (default: ~/Downloads/ring/<device>_snapshot.jpg)",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as table"),
):
    """Trigger a fresh snapshot capture and save it locally.

    Examples:
        ring snapshot get --device "Front Door"
        ring snapshot get --device "Back Yard" --output ./back-yard.jpg
    """
    try:
        client = get_client()
        result = client.get_snapshot(identifier=device, output_path=output)
        print_output(result, table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
