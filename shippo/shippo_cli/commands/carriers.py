"""Carrier account commands for Shippo CLI."""
COMMAND_CREDENTIALS = {
    "get": [
        "api_key"
    ],
    "list": [
        "api_key"
    ]
}

import typer
from typing import Optional, List

from pydantic import BaseModel

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error


app = typer.Typer(help="Manage carrier accounts", no_args_is_help=True)


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
def carriers_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of accounts to return"),
    carrier: Optional[str] = typer.Option(None, "--carrier", "-c", help="Filter by carrier (e.g., usps, fedex)"),
    service_levels: bool = typer.Option(False, "--service-levels", "-s", help="Include service levels for each carrier"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List carrier accounts configured in your Shippo account.

    Shows all carriers connected to your account (USPS, FedEx, UPS, etc.)
    with their account IDs and active status.

    Examples:
        shippo carriers list
        shippo carriers list --table
        shippo carriers list --carrier fedex
        shippo carriers list --service-levels
        shippo carriers list --properties "carrier,carrier_name,active"
    """
    try:
        client = get_client()
        accounts = client.list_carrier_accounts(
            limit=limit,
            carrier=carrier,
            include_service_levels=service_levels,
            filters=filter,
        )

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            accounts = extract_fields(accounts, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(accounts, fields, fields)
            else:
                print_table(
                    accounts,
                    ["carrier", "carrier_name", "account_id", "active", "is_shippo_account"],
                    ["Carrier", "Name", "Account ID", "Active", "Shippo Account"],
                )
        else:
            print_json(accounts)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def carriers_get(
    account_id: str = typer.Argument(..., help="The carrier account object ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Get details for a specific carrier account.

    Examples:
        shippo carriers get CARRIER_ACCOUNT_ID
        shippo carriers get CARRIER_ACCOUNT_ID --table
    """
    try:
        client = get_client()
        account = client.get_carrier_account(account_id)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            account = extract_fields([account], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([account], fields, fields)
            else:
                item_dict = model_to_dict(account)
                rows = [{"field": k, "value": str(v)} for k, v in item_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(account)

    except Exception as e:
        raise typer.Exit(handle_error(e))
