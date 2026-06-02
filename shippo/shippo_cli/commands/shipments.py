"""Shipment commands for Shippo CLI."""
COMMAND_CREDENTIALS = {
    "create": [
        "api_key"
    ],
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
from ..config import get_config
from cli_tools_shared.output import print_json, print_table, print_success, handle_error
from cli_tools_shared.filters import apply_filters


app = typer.Typer(help="Manage Shippo shipments", no_args_is_help=True)


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
def shipments_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of shipments to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List shipments.

    Examples:
        shippo shipments list
        shippo shipments list --table
        shippo shipments list --limit 10
        shippo shipments list --properties "object_id,status,address_to.city"
    """
    try:
        client = get_client()
        shipments = client.list_shipments(limit=limit, filters=filter)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            shipments = extract_fields(shipments, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(shipments, fields, fields)
            else:
                # Flatten for table display
                rows = []
                for s in shipments:
                    d = model_to_dict(s)
                    rows.append({
                        "object_id": d.get("object_id", ""),
                        "status": d.get("status", ""),
                        "to_city": d.get("address_to", {}).get("city", "") if d.get("address_to") else "",
                        "to_state": d.get("address_to", {}).get("state", "") if d.get("address_to") else "",
                        "rates_count": len(d.get("rates", [])),
                    })
                print_table(
                    rows,
                    ["object_id", "status", "to_city", "to_state", "rates_count"],
                    ["ID", "Status", "To City", "To State", "# Rates"],
                )
        else:
            print_json(shipments)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def shipments_get(
    shipment_id: str = typer.Argument(..., help="The shipment object ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Get details for a specific shipment (includes rates).

    Examples:
        shippo shipments get SHIPMENT_ID
        shippo shipments get SHIPMENT_ID --table
    """
    try:
        client = get_client()
        shipment = client.get_shipment(shipment_id)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            shipment = extract_fields([shipment], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([shipment], fields, fields)
            else:
                item_dict = model_to_dict(shipment)
                rows = [{"field": k, "value": str(v)[:80]} for k, v in item_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(shipment)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def shipments_create(
    # From address (optional - defaults from .env)
    from_name: Optional[str] = typer.Option(None, "--from-name", help="Sender full name (default: FROM_NAME env)"),
    from_street1: Optional[str] = typer.Option(None, "--from-address", "--from-street1", help="Sender street address (default: FROM_STREET1 env)"),
    from_city: Optional[str] = typer.Option(None, "--from-city", help="Sender city (default: FROM_CITY env)"),
    from_state: Optional[str] = typer.Option(None, "--from-state", help="Sender state code (default: FROM_STATE env)"),
    from_zip: Optional[str] = typer.Option(None, "--from-zip", help="Sender ZIP code (default: FROM_ZIP env)"),
    from_country: Optional[str] = typer.Option(None, "--from-country", help="Sender country (default: FROM_COUNTRY env or US)"),
    from_phone: Optional[str] = typer.Option(None, "--from-phone", help="Sender phone"),
    from_email: Optional[str] = typer.Option(None, "--from-email", help="Sender email"),
    # To address
    to_name: str = typer.Option(..., "--to-name", help="Recipient full name"),
    to_street1: str = typer.Option(..., "--to-address", "--to-street1", help="Recipient street address"),
    to_street2: Optional[str] = typer.Option(None, "--to-street2", help="Recipient address line 2 (apt, suite, unit, etc.)"),
    to_city: str = typer.Option(..., "--to-city", help="Recipient city"),
    to_state: str = typer.Option(..., "--to-state", help="Recipient state code"),
    to_zip: str = typer.Option(..., "--to-zip", help="Recipient ZIP code"),
    to_country: str = typer.Option("US", "--to-country", help="Recipient country (default: US)"),
    to_phone: Optional[str] = typer.Option(None, "--to-phone", help="Recipient phone"),
    to_email: Optional[str] = typer.Option(None, "--to-email", help="Recipient email"),
    # Parcel (with defaults)
    length: float = typer.Option(7.0, "--length", help="Parcel length in inches (default: 7)"),
    width: float = typer.Option(4.0, "--width", help="Parcel width in inches (default: 4)"),
    height: float = typer.Option(1.0, "--height", help="Parcel height in inches (default: 1)"),
    weight: float = typer.Option(8.0, "--weight", "-w", help="Parcel weight in oz (default: 8)"),
    # Output
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Create a shipment and get rates.

    Returns a shipment object containing available rates from all carriers.

    Examples:
        shippo shipments create \\
            --from-name "John Doe" --from-address "123 Main St" \\
            --from-city "San Francisco" --from-state CA --from-zip 94102 \\
            --to-name "Jane Doe" --to-address "456 Oak Ave" \\
            --to-city "Los Angeles" --to-state CA --to-zip 90001

        shippo shipments create \\
            --from-name "Sender" --from-address "100 First St" \\
            --from-city "New York" --from-state NY --from-zip 10001 \\
            --to-name "Recipient" --to-address "200 Second Ave" \\
            --to-city "Chicago" --to-state IL --to-zip 60601 \\
            --weight 16 --length 10 --width 8 --height 4
    """
    try:
        client = get_client()
        config = get_config()

        # Use defaults from config if not provided
        actual_from_name = from_name or config.from_name
        actual_from_street1 = from_street1 or config.from_street1
        actual_from_city = from_city or config.from_city
        actual_from_state = from_state or config.from_state
        actual_from_zip = from_zip or config.from_zip
        actual_from_country = from_country or config.from_country
        actual_from_phone = from_phone or config.from_phone
        actual_from_email = from_email or getattr(config, 'from_email', None)

        # Validate required from-address fields
        missing = []
        if not actual_from_name:
            missing.append("FROM_NAME")
        if not actual_from_street1:
            missing.append("FROM_STREET1")
        if not actual_from_city:
            missing.append("FROM_CITY")
        if not actual_from_state:
            missing.append("FROM_STATE")
        if not actual_from_zip:
            missing.append("FROM_ZIP")

        if missing:
            raise typer.BadParameter(
                f"Missing from-address fields. Set in .env or pass as options: {', '.join(missing)}"
            )

        shipment = client.create_shipment(
            from_name=actual_from_name,
            from_street1=actual_from_street1,
            from_city=actual_from_city,
            from_state=actual_from_state,
            from_zip=actual_from_zip,
            from_country=actual_from_country,
            from_phone=actual_from_phone,
            from_email=actual_from_email,
            to_name=to_name,
            to_street1=to_street1,
            to_street2=to_street2,
            to_city=to_city,
            to_state=to_state,
            to_zip=to_zip,
            to_country=to_country,
            to_phone=to_phone,
            to_email=to_email,
            length=length,
            width=width,
            height=height,
            weight=weight,
        )

        if table:
            # Show rates in table format
            rates = shipment.rates
            if rates:
                rows = []
                for r in rates:
                    d = model_to_dict(r)
                    rows.append({
                        "rate_id": d.get("object_id", "")[:20],
                        "provider": d.get("provider", ""),
                        "service": d.get("servicelevel", {}).get("name", "") if d.get("servicelevel") else "",
                        "amount": f"${d.get('amount', '')} {d.get('currency', '')}",
                        "days": d.get("estimated_days", ""),
                    })
                print_table(
                    rows,
                    ["rate_id", "provider", "service", "amount", "days"],
                    ["Rate ID", "Provider", "Service", "Price", "Est. Days"],
                )
            else:
                from cli_tools_shared.output import print_info
                print_info("No rates available for this shipment.")
        else:
            print_json(shipment)

    except Exception as e:
        raise typer.Exit(handle_error(e))
