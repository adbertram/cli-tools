"""Tracking commands for Shippo CLI."""
COMMAND_CREDENTIALS = {
    "get": [
        "api_key"
    ],
    "list": [
        "api_key"
    ],
    "register": [
        "api_key"
    ]
}

import typer
from typing import Optional, List

from pydantic import BaseModel

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_success, print_info, handle_error
from cli_tools_shared.filters import apply_filters
from ..parsers import format_local_time, format_date


app = typer.Typer(help="Track shipments", no_args_is_help=True)


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
def tracking_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of tracking numbers to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List tracking numbers from purchased labels.

    This retrieves tracking numbers from your label transactions.

    Examples:
        shippo tracking list
        shippo tracking list --table
        shippo tracking list --limit 10
        shippo tracking list --filter "tracking_status:eq:DELIVERED"
    """
    try:
        client = get_client()
        # Get transactions to extract tracking numbers
        transactions = client.list_transactions(limit=limit, filters=filter)

        # Extract tracking info from transactions
        tracking_list = []
        for t in transactions:
            d = model_to_dict(t)
            if d.get("tracking_number"):
                tracking_list.append({
                    "tracking_number": d.get("tracking_number", ""),
                    "carrier": d.get("rate", {}).get("provider", "") if d.get("rate") else "",
                    "tracking_status": d.get("tracking_status", ""),
                    "tracking_url": d.get("tracking_url_provider", ""),
                    "label_id": d.get("object_id", ""),
                    "created": format_local_time(d.get("object_created", "") or ""),
                })

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            tracking_list = extract_fields(tracking_list, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(tracking_list, fields, fields)
            else:
                print_table(
                    tracking_list,
                    ["tracking_number", "carrier", "tracking_status", "created"],
                    ["Tracking #", "Carrier", "Status", "Created"],
                )
        else:
            print_json(tracking_list)

        if not tracking_list:
            print_info("No tracking numbers found. Purchase labels to get tracking numbers.")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def tracking_get(
    tracking_number: str = typer.Argument(..., help="The tracking number"),
    carrier: str = typer.Option("usps", "-c", "--carrier", help="Carrier token (default: usps)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Get tracking information for a shipment.

    Examples:
        shippo tracking get 9400111899223033005011
        shippo tracking get 9400111899223033005011 --carrier usps
        shippo tracking get 1Z999AA10123456784 --carrier ups --table
    """
    try:
        client = get_client()
        tracking = client.get_tracking(tracking_number=tracking_number, carrier=carrier)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            tracking = extract_fields([tracking], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([tracking], fields, fields)
            else:
                # Show current status + history
                d = model_to_dict(tracking)

                # Current status summary
                summary = [
                    {"field": "Tracking Number", "value": d.get("tracking_number", "")},
                    {"field": "Carrier", "value": d.get("carrier", "")},
                ]

                # Add current tracking status
                status = d.get("tracking_status", {})
                if status:
                    summary.append({"field": "Status", "value": status.get("status", "")})
                    summary.append({"field": "Details", "value": status.get("status_details", "")})
                    summary.append({"field": "Date", "value": format_local_time(status.get("status_date", "") or "")})

                if d.get("eta"):
                    summary.append({"field": "ETA", "value": format_date(d.get("eta", "") or "")})

                print_table(summary, ["field", "value"], ["Field", "Value"])

                # Show tracking history if available
                history = d.get("tracking_history", [])
                if history:
                    from cli_tools_shared.output import print_info
                    print_info("\nTracking History:")
                    history_rows = []
                    for event in history:
                        history_rows.append({
                            "date": format_local_time(event.get("status_date", "") or ""),
                            "status": event.get("status", ""),
                            "details": event.get("status_details", ""),
                        })
                    print_table(
                        history_rows,
                        ["date", "status", "details"],
                        ["Date", "Status", "Details"],
                    )
        else:
            print_json(tracking)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("register")
def tracking_register(
    tracking_number: str = typer.Argument(..., help="The tracking number to register"),
    carrier: str = typer.Option("usps", "-c", "--carrier", help="Carrier token (default: usps)"),
    metadata: Optional[str] = typer.Option(None, "-m", "--metadata", help="Optional metadata string"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Register a tracking number for webhook updates.

    Use this to start receiving tracking updates via Shippo webhooks.

    Examples:
        shippo tracking register 9400111899223033005011
        shippo tracking register 9400111899223033005011 --carrier usps
        shippo tracking register 1Z999AA10123456784 --carrier ups --metadata "Order #123"
    """
    try:
        client = get_client()
        tracking = client.register_tracking(
            tracking_number=tracking_number,
            carrier=carrier,
            metadata=metadata,
        )

        if table:
            item_dict = model_to_dict(tracking)
            rows = [{"field": k, "value": str(v)[:80]} for k, v in item_dict.items() if v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(tracking)

        print_success(f"Tracking registered for {tracking_number}")

    except Exception as e:
        raise typer.Exit(handle_error(e))
