"""Merchant location commands for eBay CLI.

Uses the eBay Inventory API to manage merchant inventory locations.
API Docs: https://developer.ebay.com/api-docs/sell/inventory/resources/location/methods/getInventoryLocations
"""
COMMAND_CREDENTIALS = {
    "list": ["oauth_authorization_code"],
    "get": ["oauth_authorization_code"],
    "create": ["oauth_authorization_code"],
    "delete": ["oauth_authorization_code"],
    "enable": ["oauth_authorization_code"],
    "disable": ["oauth_authorization_code"],
}

import typer
from typing import Optional, List

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error, print_info, print_success, print_error
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError
from ..properties import validate_and_filter_properties, PropertyValidationError

app = typer.Typer(help="Manage eBay merchant inventory locations")


@app.command("list")
def locations_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(25, "--limit", "-l", help="Maximum number of locations to return"),
    filters: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter (field:op:value). Operators: eq, ne, gt, gte, lt, lte, in, nin, like, ilike, null, notnull"
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output"
    ),
):
    """
    List all merchant inventory locations.

    Merchant locations are used to specify where inventory is stored
    and where items ship from.

    Examples:
        ebay locations list
        ebay locations list --table
        ebay locations list --limit 10
        ebay locations list --filter "status:eq:ENABLED"
    """
    try:
        client = get_client()
        result = client.get_inventory_locations(limit=limit)

        locations = result.get("locations", [])

        # Transform to flat structure for filtering
        flat_locations = []
        for loc in locations:
            address = loc.get("location", {}).get("address", {})
            flat_locations.append({
                "key": loc.get("merchantLocationKey", ""),
                "name": loc.get("name", ""),
                "city": address.get("city", ""),
                "state": address.get("stateOrProvince", ""),
                "postal": address.get("postalCode", ""),
                "country": address.get("country", ""),
                "status": loc.get("merchantLocationStatus", ""),
            })

        # Validate and apply client-side filters if provided
        if filters:
            try:
                validated_filters = validate_filters(filters)
                flat_locations = apply_filters(flat_locations, validated_filters)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply properties filtering
        if properties:
            try:
                flat_locations = validate_and_filter_properties(flat_locations, properties)
            except PropertyValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        if table:
            if not flat_locations:
                print("No merchant locations found.")
                return

            print_table(
                flat_locations,
                ["key", "name", "city", "state", "postal", "country", "status"],
                ["Location Key", "Name", "City", "State", "Postal", "Country", "Status"],
            )
        else:
            print_json({"locations": flat_locations, "total": len(flat_locations)})

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def locations_get(
    location_key: str = typer.Argument(..., help="The merchant location key"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
):
    """
    Get details for a specific merchant location.

    Examples:
        ebay locations get my-warehouse
        ebay locations get my-warehouse --table
    """
    try:
        client = get_client()
        location = client.get_inventory_location(location_key)

        if table:
            address = location.get("location", {}).get("address", {})

            summary = [{
                "key": location.get("merchantLocationKey", ""),
                "name": location.get("name", ""),
                "city": address.get("city", ""),
                "state": address.get("stateOrProvince", ""),
                "postal": address.get("postalCode", ""),
                "country": address.get("country", ""),
                "status": location.get("merchantLocationStatus", ""),
                "type": ", ".join(location.get("locationTypes", [])),
            }]

            print_table(
                summary,
                ["key", "name", "city", "state", "postal", "country", "status", "type"],
                ["Location Key", "Name", "City", "State", "Postal", "Country", "Status", "Type"],
            )

            # Show full address
            print("\nFull Address:")
            print(f"  {address.get('addressLine1', '')}")
            if address.get("addressLine2"):
                print(f"  {address.get('addressLine2')}")
            print(f"  {address.get('city', '')}, {address.get('stateOrProvince', '')} {address.get('postalCode', '')}")
            print(f"  {address.get('country', '')}")
        else:
            print_json(location)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def locations_create(
    location_key: str = typer.Argument(..., help="Unique identifier for this location (e.g., 'home', 'warehouse-1')"),
    name: str = typer.Option(..., "--name", "-n", help="Display name for the location"),
    address_line1: str = typer.Option(..., "--address", "-a", help="Street address line 1"),
    city: str = typer.Option(..., "--city", "-c", help="City"),
    state: str = typer.Option(..., "--state", "-s", help="State or province"),
    postal_code: str = typer.Option(..., "--postal", "-p", help="Postal/ZIP code"),
    country: str = typer.Option("US", "--country", help="Country code (default: US)"),
    address_line2: Optional[str] = typer.Option(None, "--address2", help="Street address line 2"),
    location_type: str = typer.Option("WAREHOUSE", "--type", "-t", help="Location type: WAREHOUSE or STORE"),
    table: bool = typer.Option(False, "--table", help="Display result as table"),
):
    """
    Create a new merchant inventory location.

    The location key is a unique identifier you define. Use it when creating
    offers to specify where items ship from.

    Examples:
        ebay locations create home --name "Home Office" --address "123 Main St" \\
            --city "New York" --state "NY" --postal "10001"
        ebay locations create warehouse-1 --name "Main Warehouse" \\
            --address "456 Industrial Blvd" --city "Chicago" --state "IL" --postal "60601"
    """
    try:
        client = get_client()

        address = {
            "addressLine1": address_line1,
            "city": city,
            "stateOrProvince": state,
            "postalCode": postal_code,
            "country": country,
        }

        if address_line2:
            address["addressLine2"] = address_line2

        payload = {
            "name": name,
            "location": {
                "address": address,
            },
            "locationTypes": [location_type],
            "merchantLocationStatus": "ENABLED",
        }

        client.create_inventory_location(location_key, payload)
        print_success(f"Location '{location_key}' created.")

        if table:
            summary = [{
                "key": location_key,
                "name": name,
                "city": city,
                "state": state,
                "postal": postal_code,
                "country": country,
                "status": "ENABLED",
            }]
            print_table(
                summary,
                ["key", "name", "city", "state", "postal", "country", "status"],
                ["Location Key", "Name", "City", "State", "Postal", "Country", "Status"],
            )
        else:
            print_json({"merchantLocationKey": location_key, "status": "ENABLED"})

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def locations_delete(
    location_key: str = typer.Argument(..., help="The merchant location key to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """
    Delete a merchant inventory location.

    Note: You cannot delete a location that is associated with active listings
    or offers. You must first update those listings to use a different location.

    Examples:
        ebay locations delete old-warehouse
        ebay locations delete old-warehouse --force
    """
    try:
        client = get_client()

        # Get location info for confirmation
        if not force:
            location = client.get_inventory_location(location_key)
            location_name = location.get("name", location_key)

            if not typer.confirm(f"Delete location '{location_name}' ({location_key})?"):
                print_info("Deletion cancelled.")
                raise typer.Exit(0)

        client.delete_inventory_location(location_key)
        print_success(f"Location '{location_key}' deleted.")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("enable")
def locations_enable(
    location_key: str = typer.Argument(..., help="The merchant location key to enable"),
):
    """
    Enable a disabled merchant location.

    Examples:
        ebay locations enable my-warehouse
    """
    try:
        client = get_client()
        client.enable_inventory_location(location_key)
        print_success(f"Location '{location_key}' enabled.")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("disable")
def locations_disable(
    location_key: str = typer.Argument(..., help="The merchant location key to disable"),
):
    """
    Disable a merchant location.

    Disabled locations cannot be used for new listings but existing
    listings are not affected.

    Examples:
        ebay locations disable old-warehouse
    """
    try:
        client = get_client()
        client.disable_inventory_location(location_key)
        print_success(f"Location '{location_key}' disabled.")

    except Exception as e:
        raise typer.Exit(handle_error(e))
