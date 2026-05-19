"""Address commands for Shippo CLI."""
COMMAND_CREDENTIALS = {
    "create": [
        "api_key"
    ],
    "get": [
        "api_key"
    ],
    "list": [
        "api_key"
    ],
    "validate": [
        "api_key"
    ]
}

import typer
from typing import Optional, List

from pydantic import BaseModel

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_success, handle_error
from cli_tools_shared.filters import apply_filters


app = typer.Typer(help="Manage Shippo addresses", no_args_is_help=True)


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
def addresses_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of addresses to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List saved addresses.

    Examples:
        shippo addresses list
        shippo addresses list --table
        shippo addresses list --limit 10
        shippo addresses list --properties "object_id,name,city,state"
    """
    try:
        client = get_client()
        addresses = client.list_addresses(limit=limit, filters=filter)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            addresses = extract_fields(addresses, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(addresses, fields, fields)
            else:
                print_table(
                    addresses,
                    ["object_id", "name", "street1", "city", "state", "zip"],
                    ["ID", "Name", "Street", "City", "State", "ZIP"],
                )
        else:
            print_json(addresses)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def addresses_get(
    address_id: str = typer.Argument(..., help="The address object ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Get details for a specific address.

    Examples:
        shippo addresses get ADDRESS_ID
        shippo addresses get ADDRESS_ID --table
    """
    try:
        client = get_client()
        address = client.get_address(address_id)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            address = extract_fields([address], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([address], fields, fields)
            else:
                item_dict = model_to_dict(address)
                rows = [{"field": k, "value": str(v)} for k, v in item_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(address)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def addresses_create(
    name: str = typer.Option(..., "-n", "--name", help="Full name"),
    street1: str = typer.Option(..., "-a", "--address", "--street1", help="Street address line 1"),
    city: str = typer.Option(..., "-c", "--city", help="City"),
    state: str = typer.Option(..., "-s", "--state", help="State/province code"),
    zip_code: str = typer.Option(..., "-z", "--zip", help="Postal/ZIP code"),
    country: str = typer.Option("US", "--country", help="Country code (default: US)"),
    company: Optional[str] = typer.Option(None, "--company", help="Company name"),
    street2: Optional[str] = typer.Option(None, "--street2", help="Street address line 2"),
    phone: Optional[str] = typer.Option(None, "--phone", help="Phone number"),
    email: Optional[str] = typer.Option(None, "--email", help="Email address"),
    residential: bool = typer.Option(True, "--residential/--commercial", help="Residential address (default: True)"),
    validate: bool = typer.Option(False, "--validate", "-v", help="Validate the address"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Create a new address.

    Examples:
        shippo addresses create -n "John Doe" -a "123 Main St" -c "San Francisco" -s CA -z 94102
        shippo addresses create -n "Jane Doe" -a "456 Oak Ave" -c "Los Angeles" -s CA -z 90001 --validate
        shippo addresses create -n "ACME Inc" -a "789 Business Dr" -c "Chicago" -s IL -z 60601 --company "ACME Inc"
    """
    try:
        client = get_client()
        address = client.create_address(
            name=name,
            street1=street1,
            city=city,
            state=state,
            zip_code=zip_code,
            country=country,
            company=company,
            street2=street2,
            phone=phone,
            email=email,
            is_residential=residential,
            validate=validate,
        )

        if table:
            item_dict = model_to_dict(address)
            rows = [{"field": k, "value": str(v)} for k, v in item_dict.items() if v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(address)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("validate")
def addresses_validate(
    address_id: str = typer.Argument(..., help="The address object ID to validate"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Validate an existing address.

    Examples:
        shippo addresses validate ADDRESS_ID
        shippo addresses validate ADDRESS_ID --table
    """
    try:
        client = get_client()
        address = client.validate_address(address_id)

        if table:
            item_dict = model_to_dict(address)
            rows = [{"field": k, "value": str(v)} for k, v in item_dict.items() if v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(address)

    except Exception as e:
        raise typer.Exit(handle_error(e))
