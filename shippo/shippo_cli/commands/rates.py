"""Rate commands for Shippo CLI."""
COMMAND_CREDENTIALS = {
    "estimate": [
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
from cli_tools_shared.output import print_json, print_table, handle_error
from cli_tools_shared.filters import apply_filters


app = typer.Typer(help="Manage Shippo shipping rates", no_args_is_help=True)


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
def rates_list(
    shipment_id: str = typer.Argument(..., help="The shipment object ID to get rates for"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of rates to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List rates for a shipment.

    Examples:
        shippo rates list SHIPMENT_ID
        shippo rates list SHIPMENT_ID --table
        shippo rates list SHIPMENT_ID --filter "provider:usps"
        shippo rates list SHIPMENT_ID --filter "service:priority"
        shippo rates list SHIPMENT_ID --properties "object_id,provider,amount,estimated_days"
    """
    try:
        client = get_client()
        rates = client.list_rates(shipment_id=shipment_id, limit=limit, filters=filter)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            rates = extract_fields(rates, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(rates, fields, fields)
            else:
                rows = []
                for r in rates:
                    d = model_to_dict(r)
                    rows.append({
                        "object_id": d.get("object_id", "")[:20],
                        "provider": d.get("provider", ""),
                        "service": d.get("servicelevel", {}).get("name", "") if d.get("servicelevel") else "",
                        "amount": f"${d.get('amount', '')} {d.get('currency', '')}",
                        "estimated_days": d.get("estimated_days", ""),
                    })
                print_table(
                    rows,
                    ["object_id", "provider", "service", "amount", "estimated_days"],
                    ["Rate ID", "Provider", "Service", "Price", "Est. Days"],
                )
        else:
            print_json(rates)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def rates_get(
    rate_id: str = typer.Argument(..., help="The rate object ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Get details for a specific rate.

    Examples:
        shippo rates get RATE_ID
        shippo rates get RATE_ID --table
    """
    try:
        client = get_client()
        rate = client.get_rate(rate_id)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            rate = extract_fields([rate], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([rate], fields, fields)
            else:
                item_dict = model_to_dict(rate)
                rows = [{"field": k, "value": str(v)[:80]} for k, v in item_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(rate)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("estimate")
def rates_estimate(
    weight: float = typer.Option(..., "--weight", "-w", help="Package weight in ounces (required)"),
    to_country: str = typer.Option(..., "--to-country", "-c", help="Destination country code, e.g., US, CA, FR (required)"),
    to_zip: Optional[str] = typer.Option(None, "--to-zip", "-z", help="Destination postal code"),
    to_city: Optional[str] = typer.Option(None, "--to-city", help="Destination city"),
    to_state: Optional[str] = typer.Option(None, "--to-state", "-s", help="Destination state/province"),
    # Parcel dimensions
    length: float = typer.Option(7.0, "--length", help="Parcel length in inches (default: 7)"),
    width: float = typer.Option(4.0, "--width", help="Parcel width in inches (default: 4)"),
    height: float = typer.Option(1.0, "--height", help="Parcel height in inches (default: 1)"),
    # Customs options for international shipments
    item_description: Optional[str] = typer.Option(None, "--description", "-d", help="Item description for customs (international only, default: 'LEGO building blocks')"),
    item_value: Optional[float] = typer.Option(None, "--value", "-v", help="Item value in USD for customs (international only, default: $20)"),
    # Output options
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
):
    """
    Estimate shipping rates without creating a label.

    Creates a temporary shipment to retrieve available rates. Uses FROM address
    from environment variables (FROM_NAME, FROM_STREET1, FROM_CITY, FROM_STATE,
    FROM_ZIP, FROM_COUNTRY).

    For international destinations (non-US), customs information is automatically
    generated. You can override the defaults with --description and --value.

    Weight is in OUNCES (oz). Common conversions:
        4oz = 0.25 lbs, 8oz = 0.5 lbs, 16oz = 1 lb

    Dimensions are in INCHES. Defaults: 7" x 4" x 1"

    Examples:
        # Domestic US shipping
        shippo rates estimate --weight 8 --to-country US --to-zip 90210

        # With custom dimensions (12" x 10" x 6" box)
        shippo rates estimate --weight 32 --to-country US --to-zip 90210 \\
            --length 12 --width 10 --height 6

        # International to France (4oz package)
        shippo rates estimate --weight 4 --to-country FR

        # International with custom value
        shippo rates estimate --weight 8 --to-country FR --value 50

        # Filter by carrier
        shippo rates estimate --weight 4 --to-country FR --filter "provider:usps"
    """
    try:
        client = get_client()
        config = get_config()

        # Validate required FROM address fields from environment
        missing = []
        if not config.from_name:
            missing.append("FROM_NAME")
        if not config.from_street1:
            missing.append("FROM_STREET1")
        if not config.from_city:
            missing.append("FROM_CITY")
        if not config.from_state:
            missing.append("FROM_STATE")
        if not config.from_zip:
            missing.append("FROM_ZIP")

        if missing:
            raise typer.BadParameter(
                f"Missing FROM address fields in .env: {', '.join(missing)}"
            )

        # Detect if this is an international shipment
        is_international = to_country.upper() != config.from_country.upper()

        # Set default customs values for international shipments
        customs_description = item_description or "LEGO building blocks"
        customs_value = item_value if item_value is not None else 20.0

        # Create shipment to get rates
        # Use placeholder TO address fields if not provided
        shipment = client.create_shipment(
            from_name=config.from_name,
            from_street1=config.from_street1,
            from_city=config.from_city,
            from_state=config.from_state,
            from_zip=config.from_zip,
            from_country=config.from_country,
            from_phone=config.from_phone,
            to_name="Rate Estimate",
            to_street1="123 Main St",
            to_city=to_city or ("Beverly Hills" if to_country.upper() == "US" else "Paris"),
            to_state=to_state or ("CA" if to_country.upper() == "US" else ""),
            to_zip=to_zip or ("90210" if to_country.upper() == "US" else "75001"),
            to_country=to_country,
            to_phone=config.from_phone,
            length=length,
            width=width,
            height=height,
            weight=weight,
            # Pass customs info for international shipments
            customs_item_description=customs_description if is_international else None,
            customs_item_value=customs_value if is_international else None,
            customs_signer=config.from_name,
        )

        rates = shipment.rates or []

        # Apply filters if provided
        if filter and rates:
            rates = client._filter_rates(rates, filter)

        # Output rates
        if not rates:
            from cli_tools_shared.output import print_info
            if is_international:
                print_info("No rates available for this international destination/weight combination.")
                print_info("Try adjusting the weight or check that the destination country code is valid.")
            else:
                print_info("No rates available for this destination/weight combination.")
            return

        if json_output:
            print_json(rates)
        elif table:
            rows = []
            for r in rates:
                d = model_to_dict(r)
                rows.append({
                    "provider": d.get("provider", ""),
                    "service": d.get("servicelevel", {}).get("name", "") if d.get("servicelevel") else "",
                    "amount": f"${d.get('amount', '')} {d.get('currency', '')}",
                    "estimated_days": d.get("estimated_days", ""),
                })
            print_table(
                rows,
                ["provider", "service", "amount", "estimated_days"],
                ["Carrier", "Service", "Price", "Est. Days"],
            )
        else:
            # Default: table output for human readability
            rows = []
            for r in rates:
                d = model_to_dict(r)
                rows.append({
                    "provider": d.get("provider", ""),
                    "service": d.get("servicelevel", {}).get("name", "") if d.get("servicelevel") else "",
                    "amount": f"${d.get('amount', '')} {d.get('currency', '')}",
                    "estimated_days": d.get("estimated_days", ""),
                })
            print_table(
                rows,
                ["provider", "service", "amount", "estimated_days"],
                ["Carrier", "Service", "Price", "Est. Days"],
            )

    except Exception as e:
        raise typer.Exit(handle_error(e))
