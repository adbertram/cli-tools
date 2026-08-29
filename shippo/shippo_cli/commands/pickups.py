"""Pickup commands for Shippo CLI.

Shippo's Pickups API is create-only. There is no endpoint to list, retrieve, or
cancel a pickup, so this group exposes ``create`` only. Save the returned
``confirmation_code`` and contact USPS or DHL Express directly to change or
cancel a scheduled pickup.
"""
COMMAND_CREDENTIALS = {
    "create": [
        "api_key"
    ]
}

import typer
from datetime import datetime
from typing import Optional, List

from shippo.models import components

from ..client import get_client
from ..config import get_config
from cli_tools_shared.output import (
    command,
    print_json,
    print_table,
    print_info,
    print_error,
)


app = typer.Typer(help="Schedule USPS and DHL Express carrier pickups", no_args_is_help=True)


# Valid enum values come from the installed Shippo SDK so the CLI cannot drift
# from the API contract.
BUILDING_LOCATION_TYPES = [member.value for member in components.BuildingLocationType]
BUILDING_TYPES = [member.value for member in components.BuildingType]

OTHER_LOCATION_TYPE = components.BuildingLocationType.OTHER.value


def _parse_window_time(value: str, option: str) -> datetime:
    """Parse an ISO-8601 datetime, attaching the local offset when naive."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(
            f"{option} is not a valid ISO-8601 datetime: {value!r} ({exc})"
        )
    if parsed.tzinfo is None:
        # A naive value means local wall-clock time; attach the local offset so
        # Shippo receives an unambiguous instant.
        parsed = parsed.astimezone()
    return parsed


@app.command("create")
@command
def pickups_create(
    carrier_account: str = typer.Option(
        ...,
        "--carrier-account",
        help="USPS or DHL Express carrier account object ID (see: shippo carriers list)",
    ),
    transactions: Optional[List[str]] = typer.Option(
        None,
        "--transaction",
        help="Transaction (label) object ID to be collected; repeat for multiple labels",
    ),
    start: str = typer.Option(
        ...,
        "--start",
        help="Start of the requested pickup window, ISO-8601 (e.g. 2026-08-29T10:00:00)",
    ),
    end: str = typer.Option(
        ...,
        "--end",
        help="End of the requested pickup window, ISO-8601 (e.g. 2026-08-29T16:00:00)",
    ),
    location_type: str = typer.Option(
        "Front Door",
        "--location-type",
        help=f"Where the carrier collects the parcels. One of: {', '.join(BUILDING_LOCATION_TYPES)}",
    ),
    building_type: Optional[str] = typer.Option(
        None,
        "--building-type",
        help=f"Building type. One of: {', '.join(BUILDING_TYPES)}",
    ),
    instructions: Optional[str] = typer.Option(
        None,
        "--instructions",
        help=f"Pickup instructions; required when --location-type is '{OTHER_LOCATION_TYPE}'",
    ),
    from_name: Optional[str] = typer.Option(None, "--from-name", help="Pickup contact name (default: FROM_NAME env)"),
    from_company: Optional[str] = typer.Option(None, "--from-company", help="Pickup company name (default: FROM_COMPANY env)"),
    from_street1: Optional[str] = typer.Option(None, "--from-address", "--from-street1", help="Pickup street address (default: FROM_STREET1 env)"),
    from_street2: Optional[str] = typer.Option(None, "--from-street2", help="Pickup address line 2"),
    from_city: Optional[str] = typer.Option(None, "--from-city", help="Pickup city (default: FROM_CITY env)"),
    from_state: Optional[str] = typer.Option(None, "--from-state", help="Pickup state code (default: FROM_STATE env)"),
    from_zip: Optional[str] = typer.Option(None, "--from-zip", help="Pickup ZIP code (default: FROM_ZIP env)"),
    from_country: Optional[str] = typer.Option(None, "--from-country", help="Pickup country (default: FROM_COUNTRY env or US)"),
    from_phone: Optional[str] = typer.Option(None, "--from-phone", help="Pickup contact phone (default: FROM_PHONE env)"),
    from_email: Optional[str] = typer.Option(None, "--from-email", help="Pickup contact email (default: FROM_EMAIL env)"),
    metadata: Optional[str] = typer.Option(None, "--metadata", "-m", help="Optional metadata string"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Schedule a carrier pickup for already-purchased labels.

    Shippo schedules pickups for USPS and DHL Express only. Book FedEx and UPS
    pickups through their own carrier tools.

    The pickup window must be on the label's ship date (today or tomorrow), and
    Shippo cannot retrieve or cancel a pickup afterwards -- save the returned
    confirmation code and contact the carrier directly to change or cancel it.

    Examples:
        shippo pickups create \\
            --carrier-account CARRIER_ACCOUNT_ID \\
            --transaction TRANSACTION_ID \\
            --start 2026-08-29T10:00:00 --end 2026-08-29T16:00:00

        shippo pickups create \\
            --carrier-account CARRIER_ACCOUNT_ID \\
            --transaction TRANSACTION_ID --transaction OTHER_TRANSACTION_ID \\
            --start 2026-08-29T10:00:00 --end 2026-08-29T16:00:00 \\
            --location-type "Front Door" --from-company "ACME Inc" --table
    """
    if not transactions:
        raise typer.BadParameter(
            "At least one --transaction is required. Pass the object ID of a "
            "purchased label (see: shippo labels list)."
        )

    start_time = _parse_window_time(start, "--start")
    end_time = _parse_window_time(end, "--end")
    if end_time <= start_time:
        raise typer.BadParameter(
            f"--end must be after --start. Got --start {start_time.isoformat()} "
            f"and --end {end_time.isoformat()}."
        )

    if location_type not in BUILDING_LOCATION_TYPES:
        raise typer.BadParameter(
            f"--location-type {location_type!r} is not valid. Valid values: "
            f"{', '.join(BUILDING_LOCATION_TYPES)}"
        )

    if building_type is not None and building_type not in BUILDING_TYPES:
        raise typer.BadParameter(
            f"--building-type {building_type!r} is not valid. Valid values: "
            f"{', '.join(BUILDING_TYPES)}"
        )

    if location_type == OTHER_LOCATION_TYPE and not instructions:
        raise typer.BadParameter(
            f"--instructions is required when --location-type is '{OTHER_LOCATION_TYPE}'."
        )

    config = get_config()
    address = {
        "name": from_name or config.from_name,
        "company": from_company or config.from_company,
        "street1": from_street1 or config.from_street1,
        "street2": from_street2,
        "city": from_city or config.from_city,
        "state": from_state or config.from_state,
        "zip": from_zip or config.from_zip,
        "country": from_country or config.from_country,
        "phone": from_phone or config.from_phone,
        "email": from_email or config.from_email,
    }

    missing = [
        env_key
        for field, env_key in (
            ("name", "FROM_NAME"),
            ("street1", "FROM_STREET1"),
            ("city", "FROM_CITY"),
            ("state", "FROM_STATE"),
            ("zip", "FROM_ZIP"),
            ("country", "FROM_COUNTRY"),
        )
        if not address[field]
    ]
    if missing:
        raise typer.BadParameter(
            "Missing pickup-address fields. Set in .env or pass as options: "
            f"{', '.join(missing)}"
        )

    client = get_client()
    pickup = client.create_pickup(
        carrier_account=carrier_account,
        transactions=list(transactions),
        requested_start_time=start_time,
        requested_end_time=end_time,
        address=address,
        building_location_type=location_type,
        building_type=building_type,
        instructions=instructions,
        metadata=metadata,
    )

    if table:
        item_dict = pickup.model_dump()
        rows = [{"field": k, "value": str(v)[:80]} for k, v in item_dict.items() if v is not None]
        print_table(rows, ["field", "value"], ["Field", "Value"])
    else:
        print_json(pickup)

    # Shippo returns HTTP 201 with status ERROR for rejected pickups (a missing
    # or invalid company name is the most common cause). That is a failure.
    if pickup.status == "ERROR":
        if pickup.messages:
            for message in pickup.messages:
                print_error(message)
        else:
            print_error(
                "Shippo returned pickup status ERROR with no messages; the pickup was not scheduled."
            )
        raise typer.Exit(1)

    if pickup.confirmation_code:
        print_info(f"Confirmation code: {pickup.confirmation_code}")
    if pickup.confirmed_start_time and pickup.confirmed_end_time:
        print_info(
            f"Confirmed window: {pickup.confirmed_start_time} to {pickup.confirmed_end_time}"
        )
    if pickup.cancel_by_time:
        print_info(f"Cancel by: {pickup.cancel_by_time}")
    print_info(
        "Shippo cannot retrieve or cancel a pickup after creation. Save the "
        "confirmation code and contact the carrier directly to change or cancel it."
    )
