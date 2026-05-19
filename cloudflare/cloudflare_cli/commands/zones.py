"""Zones commands for Cloudflare CLI."""
import typer
from typing import Optional, List
from enum import Enum

from pydantic import BaseModel

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error, print_success
from cli_tools_shared import FilterMap


class SecurityLevel(str, Enum):
    """Cloudflare security level settings."""
    OFF = "off"
    ESSENTIALLY_OFF = "essentially_off"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNDER_ATTACK = "under_attack"


app = typer.Typer(help="Manage Cloudflare zones", no_args_is_help=True)

# Configure filter mappings for Cloudflare zones API
zone_filter_map = FilterMap()
zone_filter_map.register_api_translator("status", lambda op, val: {"status": val})
zone_filter_map.register_api_translator("name", lambda op, val: {"name": val})


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
def zones_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of zones to return (max 50)"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """
    List Cloudflare zones.

    Examples:
        cloudflare zones list
        cloudflare zones list --table
        cloudflare zones list --limit 10
        cloudflare zones list --filter "status:active"
        cloudflare zones list --properties "id,name,status"
    """
    try:
        client = get_client()
        # Returns List[Zone] models
        zones = client.list_zones(limit=limit, filters=filter)

        # Apply property field selection with dot-notation support
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            zones = extract_fields(zones, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(zones, fields, fields)
            else:
                # Default table columns
                print_table(
                    zones,
                    ["id", "name", "status"],
                    ["ID", "Name", "Status"],
                )
        else:
            print_json(zones)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def zones_get(
    zone_id: str = typer.Argument(..., help="The zone ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """
    Get details for a specific zone.

    Examples:
        cloudflare zones get ZONE_ID
        cloudflare zones get ZONE_ID --table
        cloudflare zones get ZONE_ID --properties "id,name,status"
    """
    try:
        client = get_client()
        # Returns ZoneDetail model
        zone = client.get_zone(zone_id)

        # Apply property field selection with dot-notation support
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            zone = extract_fields([zone], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([zone], fields, fields)
            else:
                # Convert model to key-value table
                zone_dict = model_to_dict(zone)
                rows = [{"field": k, "value": str(v)} for k, v in zone_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(zone)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def zones_update(
    zone_id: str = typer.Argument(..., help="The zone ID"),
    security_level: Optional[SecurityLevel] = typer.Option(
        None, "--security-level", "-s", help="Set security level (off, essentially_off, low, medium, high, under_attack)"
    ),
):
    """
    Update zone settings.

    Examples:
        cloudflare zones update ZONE_ID --security-level high
        cloudflare zones update ZONE_ID --security-level under_attack
        cloudflare zones update ZONE_ID -s medium
    """
    if security_level is None:
        typer.echo("Error: At least one setting must be specified", err=True)
        raise typer.Exit(1)

    try:
        client = get_client()
        updated = []

        if security_level is not None:
            result = client.set_security_level(zone_id, security_level.value)
            updated.append(f"security_level: {result.get('value', security_level.value)}")

        print_success(f"Zone {zone_id} updated: {', '.join(updated)}")

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "get": [
        "api_key"
    ],
    "list": [
        "api_key"
    ],
    "update": [
        "api_key"
    ]
}
