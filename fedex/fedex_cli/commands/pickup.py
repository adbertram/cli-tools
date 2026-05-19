"""Pickup commands for FedEx CLI.

Commands for checking pickup availability, scheduling pickups, and canceling them.
"""
import typer
from typing import Optional

from ..client import get_client
from ..config import get_config
from cli_tools_shared.output import print_json, print_table, print_success, print_error, handle_error


app = typer.Typer(help="Manage FedEx pickups", no_args_is_help=True)

# Credential type mapping for each command
COMMAND_CREDENTIALS = {
    "availability": [
        "oauth"
    ],
    "cancel": [
        "oauth"
    ],
    "schedule": [
        "oauth"
    ]
}



@app.command("availability")
def pickup_availability(
    street: Optional[str] = typer.Option(None, "--street", "-s", help="Street address (default from .env)"),
    city: Optional[str] = typer.Option(None, "--city", "-c", help="City (default from .env)"),
    state: Optional[str] = typer.Option(None, "--state", help="State code (default from .env)"),
    postal_code: Optional[str] = typer.Option(None, "--postal", "-p", help="Postal/ZIP code (default from .env)"),
    carrier: Optional[str] = typer.Option(None, "--carrier", help="Carrier: FDXE (Express) or FDXG (Ground) (default from .env)"),
    pickup_date: Optional[str] = typer.Option(None, "--date", "-d", help="Pickup date (YYYY-MM-DD), defaults to today"),
    ready_time: str = typer.Option("15:30:00", "--ready-time", help="Time package ready (HH:MM:SS)"),
    close_time: str = typer.Option("18:00:00", "--close-time", help="Latest pickup time (HH:MM:SS)"),
    residential: Optional[bool] = typer.Option(None, "--residential", "-r", help="Residential address (default from .env)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Check pickup availability for a location.

    Address defaults to values in .env file if not specified.

    Examples:
        fedex pickup availability
        fedex pickup availability --carrier FDXG
        fedex pickup availability --street "123 Main St" --city "Columbus" --state OH --postal 43215
    """
    try:
        config = get_config()

        # Use defaults from config if not provided
        street = street or config.default_street
        city = city or config.default_city
        state = state or config.default_state
        postal_code = postal_code or config.default_postal
        carrier = carrier or config.default_carrier
        if residential is None:
            residential = config.default_residential

        # Validate required fields
        missing = []
        if not street:
            missing.append("--street")
        if not city:
            missing.append("--city")
        if not state:
            missing.append("--state")
        if not postal_code:
            missing.append("--postal")

        if missing:
            print_error(f"Missing required options: {', '.join(missing)}. Set defaults in .env or provide on command line.")
            raise typer.Exit(1)

        client = get_client()
        options = client.check_availability(
            street=street,
            city=city,
            state=state,
            postal_code=postal_code,
            carrier=carrier,
            pickup_date=pickup_date,
            package_ready_time=ready_time,
            close_time=close_time,
            residential=residential,
        )

        if table:
            print_table(
                options,
                ["carrier", "available", "pickup_date", "cut_off_time", "default_ready_time"],
                ["Carrier", "Available", "Date", "Cutoff", "Ready Time"],
            )
        else:
            print_json(options)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("schedule")
def pickup_schedule(
    account: Optional[str] = typer.Option(None, "--account", "-a", help="FedEx account number (default from .env)"),
    street: Optional[str] = typer.Option(None, "--street", "-s", help="Street address (default from .env)"),
    city: Optional[str] = typer.Option(None, "--city", "-c", help="City (default from .env)"),
    state: Optional[str] = typer.Option(None, "--state", help="State code (default from .env)"),
    postal_code: Optional[str] = typer.Option(None, "--postal", "-p", help="Postal/ZIP code (default from .env)"),
    carrier: Optional[str] = typer.Option(None, "--carrier", help="Carrier: FDXE (Express) or FDXG (Ground) (default from .env)"),
    packages: int = typer.Option(1, "--packages", "-n", help="Number of packages"),
    weight: Optional[float] = typer.Option(None, "--weight", "-w", help="Total weight"),
    weight_units: str = typer.Option("LB", "--weight-units", help="Weight units: LB or KG"),
    ready_time: str = typer.Option("15:30:00", "--ready-time", help="Time package ready (HH:MM:SS)"),
    close_time: str = typer.Option("18:00:00", "--close-time", help="Latest pickup time (HH:MM:SS)"),
    remarks: Optional[str] = typer.Option(None, "--remarks", help="Delivery instructions (max 60 chars)"),
    residential: Optional[bool] = typer.Option(None, "--residential", "-r", help="Residential address (default from .env)"),
    package_location: Optional[str] = typer.Option(None, "--package-location", help="Package location: FRONT, REAR, SIDE, NONE (default from .env)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Schedule a new FedEx pickup.

    Address defaults to values in .env file if not specified.

    Examples:
        fedex pickup schedule --account 123456789
        fedex pickup schedule -a 123456789 --packages 2 --weight 10.5
        fedex pickup schedule -a 123456789 --street "123 Main St" --city "Columbus" --state OH --postal 43215
    """
    try:
        config = get_config()

        # Use defaults from config if not provided
        account = account or config.default_account
        street = street or config.default_street
        city = city or config.default_city
        state = state or config.default_state
        postal_code = postal_code or config.default_postal
        carrier = carrier or config.default_carrier
        if residential is None:
            residential = config.default_residential
        package_location = package_location or config.default_package_location or "FRONT"

        # Validate required fields
        missing = []
        if not account:
            missing.append("--account")
        if not street:
            missing.append("--street")
        if not city:
            missing.append("--city")
        if not state:
            missing.append("--state")
        if not postal_code:
            missing.append("--postal")

        if missing:
            print_error(f"Missing required options: {', '.join(missing)}. Set defaults in .env or provide on command line.")
            raise typer.Exit(1)

        client = get_client()
        pickup = client.schedule_pickup(
            account_number=account,
            street=street,
            city=city,
            state=state,
            postal_code=postal_code,
            carrier=carrier,
            package_count=packages,
            package_weight=weight,
            weight_units=weight_units,
            ready_time=ready_time,
            close_time=close_time,
            remarks=remarks,
            residential=residential,
            package_location=package_location,
        )

        print_success(f"Pickup scheduled: {pickup.pickup_confirmation_code}")

        if table:
            print_table(
                [pickup],
                ["pickup_confirmation_code", "carrier", "scheduled_date", "location"],
                ["Confirmation", "Carrier", "Date", "Location"],
            )
        else:
            print_json(pickup)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("cancel")
def pickup_cancel(
    confirmation_code: str = typer.Argument(..., help="Pickup confirmation code"),
    account: Optional[str] = typer.Option(None, "--account", "-a", help="FedEx account number (default from .env)"),
    date: str = typer.Option(..., "--date", "-d", help="Scheduled pickup date (YYYY-MM-DD)"),
    carrier: Optional[str] = typer.Option(None, "--carrier", help="Carrier: FDXE (Express) or FDXG (Ground) (default from .env)"),
    location: Optional[str] = typer.Option(None, "--location", "-l", help="Location code (required for Express)"),
):
    """
    Cancel a scheduled pickup.

    Examples:
        fedex pickup cancel ABC123 --account 123456789 --date 2024-01-15
        fedex pickup cancel ABC123 -a 123456789 -d 2024-01-15 --carrier FDXG
        fedex pickup cancel ABC123 -a 123456789 -d 2024-01-15 --location NQAA
    """
    try:
        config = get_config()
        account = account or config.default_account
        carrier = carrier or config.default_carrier

        if not account:
            print_error("Missing required option: --account. Set FEDEX_DEFAULT_ACCOUNT in .env or provide on command line.")
            raise typer.Exit(1)

        client = get_client()
        result = client.cancel_pickup(
            account_number=account,
            confirmation_code=confirmation_code,
            scheduled_date=date,
            carrier=carrier,
            location=location,
        )

        print_success(result.get("message", "Pickup cancelled"))
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))
