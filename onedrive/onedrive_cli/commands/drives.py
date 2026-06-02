"""Drives commands for OneDrive CLI.

List and get details about OneDrive drives (personal drives, shared drives).
"""
import typer
from typing import Optional, List

from pydantic import BaseModel

from ..client import get_client
from ..filter_map import apply_filters
from cli_tools_shared.output import print_json, print_table, handle_error


app = typer.Typer(help="Manage OneDrive drives", no_args_is_help=True)


def model_to_dict(item):
    """Convert model or dict to dict for field extraction."""
    if isinstance(item, BaseModel):
        return item.model_dump()
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
def drives_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of drives to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List all drives accessible to the authenticated user.

    Shows personal OneDrive and any shared drives the user can access.

    Examples:
        onedrive drives list
        onedrive drives list --table
        onedrive drives list --properties "id,name,driveType"
        onedrive drives list --limit 10
    """
    try:
        client = get_client()
        drives = client.list_drives(limit=limit)

        if filter:
            drives = apply_filters([model_to_dict(drive) for drive in drives], filter)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            drives = extract_fields(drives, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(drives, fields, fields)
            else:
                print_table(
                    drives,
                    ["id", "name", "drive_type"],
                    ["ID", "Name", "Drive Type"],
                )
        else:
            print_json(drives)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def drives_get(
    drive_id: str = typer.Argument(..., help="The drive ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Get details for a specific drive.

    Examples:
        onedrive drives get DRIVE_ID
        onedrive drives get DRIVE_ID --table
        onedrive drives get DRIVE_ID --properties "id,name,quota"
    """
    try:
        client = get_client()
        drive = client.get_drive(drive_id)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            drive = extract_fields([drive], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([drive], fields, fields)
            else:
                # Convert model to key-value table
                drive_dict = model_to_dict(drive)
                rows = [{"field": k, "value": str(v)} for k, v in drive_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(drive)

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ]
}
