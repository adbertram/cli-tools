"""Shipping quote commands for eBay CLI.

Uses the eBay Logistics API to get shipping rate quotes.
API Docs: https://developer.ebay.com/api-docs/sell/logistics/resources/shipping_quote/methods/createShippingQuote
"""
COMMAND_CREDENTIALS = {
    "create": ["oauth_authorization_code"],
}

import typer
from typing import Optional, Dict, Any

from ..client import get_client
from ..config import get_config
from cli_tools_shared.output import print_json, print_table, handle_error, print_error
from ..parsers import format_local_time, format_date

app = typer.Typer(help="Manage eBay shipping quotes")


@app.command("create")
def shipping_quote_create(
    to_name: str = typer.Option(..., help="Recipient full name"),
    to_street: str = typer.Option(..., help="Recipient street address"),
    to_city: str = typer.Option(..., help="Recipient city"),
    to_state: str = typer.Option(..., help="Recipient state/province code"),
    to_zip: str = typer.Option(..., help="Recipient postal code"),
    to_country: str = typer.Option("US", help="Recipient country code"),
    to_phone: Optional[str] = typer.Option(None, help="Recipient phone number"),

    from_name: Optional[str] = typer.Option(None, help="Sender full name (defaults to profile config)"),
    from_street: Optional[str] = typer.Option(None, help="Sender street address (defaults to profile config)"),
    from_city: Optional[str] = typer.Option(None, help="Sender city (defaults to profile config)"),
    from_state: Optional[str] = typer.Option(None, help="Sender state/province code (defaults to profile config)"),
    from_zip: Optional[str] = typer.Option(None, help="Sender postal code (defaults to profile config)"),
    from_country: Optional[str] = typer.Option(None, help="Sender country code (defaults to profile config)"),
    from_phone: Optional[str] = typer.Option(None, help="Sender phone number (defaults to profile config)"),

    weight: float = typer.Option(..., help="Package weight value"),
    weight_unit: str = typer.Option("POUND", help="Weight unit: POUND, OUNCE, KILOGRAM, GRAM"),

    length: float = typer.Option(..., help="Package length"),
    width: float = typer.Option(..., help="Package width"),
    height: float = typer.Option(..., help="Package height"),
    dimension_unit: str = typer.Option("INCH", help="Dimension unit: INCH, CENTIMETER"),

    order_id: str = typer.Option(..., help="eBay order ID (required by Logistics API)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display results as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """
    Get USPS shipping rate quotes for a package.

    Returns available rates with pricing and estimated delivery dates.
    Quotes expire after ~10 minutes. An eBay order ID is required.

    Examples:
        ebay shipping-quote create --order-id 04-08365-42542 \\
            --to-name "Jane Smith" --to-street "456 Oak Ave" \\
            --to-city "New York" --to-state NY --to-zip 10001 \\
            --weight 1.5 --length 10 --width 8 --height 4
    """
    try:
        config = get_config(profile=profile)
        client = get_client(profile=profile)

        # Build Logistics API payload with correct field names
        # Use provided options or fall back to profile config
        f_name = from_name or config.get_from_name()
        f_street = from_street or config.get_from_street()
        f_city = from_city or config.get_from_city()
        f_state = from_state or config.get_from_state()
        f_zip = from_zip or config.get_from_zip()
        f_country = from_country or config.get_from_country()
        f_phone = from_phone or config.get_from_phone()

        if not all([f_name, f_street, f_city, f_state, f_zip, f_country]):
            print_error("Missing sender address. Provide via options or configure in profile.")
            raise typer.Exit(1)

        ship_from: Dict[str, Any] = {
            "fullName": f_name,
            "contactAddress": {
                "addressLine1": f_street,
                "city": f_city,
                "stateOrProvince": f_state,
                "postalCode": f_zip,
                "countryCode": f_country,
            },
        }
        if f_phone:
            ship_from["primaryPhone"] = {"phoneNumber": f_phone}

        ship_to: Dict[str, Any] = {
            "fullName": to_name,
            "contactAddress": {
                "addressLine1": to_street,
                "city": to_city,
                "stateOrProvince": to_state,
                "postalCode": to_zip,
                "countryCode": to_country,
            },
        }
        if to_phone:
            ship_to["primaryPhone"] = {"phoneNumber": to_phone}

        package_spec: Dict[str, Any] = {
            "weight": {"value": str(weight), "unit": weight_unit},
            "dimensions": {
                "length": str(length),
                "width": str(width),
                "height": str(height),
                "unit": dimension_unit,
            },
        }

        payload: Dict[str, Any] = {
            "shipFrom": ship_from,
            "shipTo": ship_to,
            "packageSpecification": package_spec,
        }

        payload["orders"] = [{"channel": "EBAY", "orderId": order_id}]

        result = client.create_shipping_quote(payload)

        if table:
            rates = result.get("rates", [])
            table_data = []
            for rate in rates:
                base = rate.get("baseShippingCost", {})
                options = rate.get("additionalOptions", [])
                option_str = ", ".join(
                    f"{o['optionType']}(+${o.get('additionalCost', {}).get('value', '?')})"
                    for o in options
                )
                d_min = format_date(rate.get("minEstimatedDeliveryDate", ""))
                d_max = format_date(rate.get("maxEstimatedDeliveryDate", ""))
                delivery = f"{d_min} - {d_max}" if d_min else ""

                table_data.append({
                    "service": rate.get("shippingServiceName", ""),
                    "cost": f"${base.get('value', '?')} {base.get('currency', '')}",
                    "delivery": delivery,
                    "options": option_str,
                    "recommendations": ", ".join(rate.get("rateRecommendation", [])),
                    "rate_id": rate.get("rateId", ""),
                })

            if not table_data:
                print_error("No shipping rates returned.")
            else:
                print_table(
                    table_data,
                    ["service", "cost", "delivery", "options", "recommendations", "rate_id"],
                    ["Service", "Cost", "Est. Delivery", "Add-ons", "Recommendations", "Rate ID"],
                )
                print_error(f"\nQuote ID: {result.get('shippingQuoteId', '')}")
                print_error(f"Expires: {format_local_time(result.get('expirationDate', ''))}")
        else:
            print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))

