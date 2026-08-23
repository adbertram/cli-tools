"""Pickup commands for UPS CLI."""

from typing import List, Optional

import typer
from cli_tools_shared.filters import FilterValidationError, apply_filters, apply_properties_filter, validate_filters
from cli_tools_shared.output import command, handle_error, print_error, print_info, print_json, print_success, print_table

from .client import build_pickup_payload, get_client
from .config import get_config

app = typer.Typer(help="Schedule and inspect UPS pickups", no_args_is_help=True)

COMMAND_CREDENTIALS = {
    "list": ["oauth"],
    "get": ["oauth"],
    "schedule": ["no_auth"],
}

PICKUP_COLUMNS = ["prn", "service_date", "status_message", "pickup_type", "contact_name", "reference_number"]
SCHEDULE_COLUMNS = ["prn", "status_code", "status_description", "rate_status_description"]


def _property_fields(properties: Optional[str]) -> Optional[List[str]]:
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None


def _validate(filters: Optional[List[str]]) -> None:
    if not filters:
        return
    try:
        validate_filters(filters)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


def _render_records(
    rows: List[dict],
    *,
    table: bool,
    properties: Optional[str],
    empty: str,
    default_columns: List[str],
) -> None:
    fields = _property_fields(properties)
    if fields:
        rows = apply_properties_filter(rows, properties)
    if not table:
        print_json(rows)
        return
    if not rows:
        print_info(empty)
        return
    columns = fields or [column for column in default_columns if any(column in row for row in rows)]
    print_table(rows, columns, [column.replace("_", " ").title() for column in columns])


def _render_record(row: dict, *, table: bool, properties: Optional[str]) -> None:
    fields = _property_fields(properties)
    if fields:
        row = apply_properties_filter([row], properties)[0]
    if not table:
        print_json(row)
        return
    if fields:
        print_table([row], fields, [field.replace("_", " ").title() for field in fields])
        return
    print_table(
        [{"field": key, "value": str(value)} for key, value in row.items()],
        ["field", "value"],
        ["Field", "Value"],
    )


def _required(value: Optional[str], option: str) -> str:
    if value:
        return value
    raise typer.BadParameter(f"{option} is required; set the matching UPS_DEFAULT_* config value or pass {option}.")


def _schedule_value(
    value: Optional[str],
    option: str,
    *,
    dry_run: bool,
    placeholder: str,
    missing: List[str],
) -> str:
    if value:
        return value
    if dry_run:
        missing.append(option)
        return placeholder
    return _required(value, option)


@app.command("list")
@command
def list_pickups(
    account: Optional[str] = typer.Option(None, "--account", "-a", help="UPS account number (default from config)"),
    pickup_type: str = typer.Option("oncall", "--pickup-type", help="Pickup type: oncall, smart, or both"),
    version: Optional[str] = typer.Option(None, "--version", help="UPS Pickup API version (default from config)"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of pickups"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List pending UPS pickups for an account."""
    _validate(filter)
    config = get_config()
    account_number = _required(account or config.account_number, "--account")
    rows = get_client().list_pickups(account_number=account_number, pickup_type=pickup_type, version=version)
    if filter:
        rows = apply_filters(rows, filter)
    if limit >= 0:
        rows = rows[:limit]
    _render_records(
        rows,
        table=table,
        properties=properties,
        empty="No pending UPS pickups found.",
        default_columns=PICKUP_COLUMNS,
    )


@app.command("get")
@command
def get_pickup(
    prn: str = typer.Argument(..., help="UPS pickup request number"),
    account: Optional[str] = typer.Option(None, "--account", "-a", help="UPS account number (default from config)"),
    pickup_type: str = typer.Option("oncall", "--pickup-type", help="Pickup type: oncall, smart, or both"),
    version: Optional[str] = typer.Option(None, "--version", help="UPS Pickup API version (default from config)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one pending UPS pickup by PRN."""
    config = get_config()
    account_number = _required(account or config.account_number, "--account")
    row = get_client().get_pickup(prn=prn, account_number=account_number, pickup_type=pickup_type, version=version)
    _render_record(row, table=table, properties=properties)


@app.command("schedule")
@command
def schedule_pickup(
    account: Optional[str] = typer.Option(None, "--account", "-a", help="UPS account number (default from config)"),
    account_country: Optional[str] = typer.Option(None, "--account-country", help="UPS account country code"),
    pickup_date: Optional[str] = typer.Option(None, "--date", "-d", help="Pickup date: YYYY-MM-DD or YYYYMMDD (default today/next business day)"),
    ready_time: str = typer.Option("15:30", "--ready-time", help="Earliest ready time: HHMM, HH:MM, or HH:MM:SS"),
    close_time: str = typer.Option("18:00", "--close-time", help="Latest close time: HHMM, HH:MM, or HH:MM:SS"),
    company: Optional[str] = typer.Option(None, "--company", help="Pickup company/name (default from config)"),
    contact: Optional[str] = typer.Option(None, "--contact", help="Pickup contact name (default from config)"),
    street: Optional[str] = typer.Option(None, "--street", "-s", help="Pickup street address (default from config)"),
    city: Optional[str] = typer.Option(None, "--city", "-c", help="Pickup city (default from config)"),
    state: Optional[str] = typer.Option(None, "--state", help="Pickup state/province (default from config)"),
    postal: Optional[str] = typer.Option(None, "--postal", "-z", help="Pickup postal code (default from config)"),
    country: Optional[str] = typer.Option(None, "--country", help="Pickup country code"),
    phone: Optional[str] = typer.Option(None, "--phone", help="Pickup phone number (default from config)"),
    phone_extension: Optional[str] = typer.Option(None, "--phone-extension", help="Pickup phone extension"),
    residential: Optional[bool] = typer.Option(None, "--residential", help="Pickup address is residential"),
    pickup_point: Optional[str] = typer.Option(None, "--pickup-point", help="Package pickup point/location"),
    packages: int = typer.Option(1, "--packages", "-n", help="Number of packages"),
    weight: Optional[float] = typer.Option(None, "--weight", "-w", help="Total shipment weight"),
    weight_unit: Optional[str] = typer.Option(None, "--weight-unit", help="Weight unit, usually LBS or KGS"),
    service_code: Optional[str] = typer.Option(None, "--service-code", help="UPS service code (default 003 Ground)"),
    container_code: Optional[str] = typer.Option(None, "--container-code", help="UPS container code (default 01 package)"),
    destination_country: Optional[str] = typer.Option(None, "--destination-country", help="Destination country code"),
    payment_method: Optional[str] = typer.Option(None, "--payment-method", help="UPS payment method code (default 01)"),
    special_instruction: Optional[str] = typer.Option(None, "--special-instruction", help="Pickup instructions"),
    reference_number: Optional[str] = typer.Option(None, "--reference-number", help="Reference number"),
    rate_pickup: bool = typer.Option(False, "--rate", help="Ask UPS to rate pickup charges in the response"),
    version: Optional[str] = typer.Option(None, "--version", help="UPS Pickup API version (default from config)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the UPS request without scheduling"),
    table: bool = typer.Option(False, "--table", "-t", help="Display response as table"),
):
    """Schedule a UPS pickup."""
    try:
        config = get_config()
        missing_placeholders: List[str] = []
        payload = build_pickup_payload(
            account_number=_schedule_value(
                account or config.account_number,
                "--account",
                dry_run=dry_run,
                placeholder="000000",
                missing=missing_placeholders,
            ),
            account_country=account_country or config.account_country,
            pickup_date=pickup_date,
            ready_time=ready_time,
            close_time=close_time,
            company_name=_schedule_value(
                company or config.default_company,
                "--company",
                dry_run=dry_run,
                placeholder="Geek Life",
                missing=missing_placeholders,
            ),
            contact_name=_schedule_value(
                contact or config.default_contact,
                "--contact",
                dry_run=dry_run,
                placeholder="Adam",
                missing=missing_placeholders,
            ),
            street=_schedule_value(
                street or config.default_street,
                "--street",
                dry_run=dry_run,
                placeholder="123 Example St",
                missing=missing_placeholders,
            ),
            city=_schedule_value(
                city or config.default_city,
                "--city",
                dry_run=dry_run,
                placeholder="Example",
                missing=missing_placeholders,
            ),
            state=_schedule_value(
                state or config.default_state,
                "--state",
                dry_run=dry_run,
                placeholder="XX",
                missing=missing_placeholders,
            ),
            postal_code=_schedule_value(
                postal or config.default_postal,
                "--postal",
                dry_run=dry_run,
                placeholder="00000",
                missing=missing_placeholders,
            ),
            country=country or config.default_country,
            phone=_schedule_value(
                phone or config.default_phone,
                "--phone",
                dry_run=dry_run,
                placeholder="0000000000",
                missing=missing_placeholders,
            ),
            residential=config.default_residential if residential is None else residential,
            pickup_point=pickup_point or config.default_pickup_point,
            package_count=packages,
            weight=weight if weight is not None else config.default_weight,
            weight_unit=weight_unit or config.default_weight_unit,
            service_code=service_code or config.default_service_code,
            container_code=container_code or config.default_container_code,
            destination_country=destination_country or config.default_destination_country,
            payment_method=payment_method or config.default_payment_method,
            special_instruction=special_instruction,
            reference_number=reference_number,
            rate_pickup=rate_pickup,
            phone_extension=phone_extension,
        )
        endpoint_version = version or config.api_version
        if dry_run:
            print_json(
                {
                    "dry_run": True,
                    "method": "POST",
                    "endpoint": f"/pickupcreation/{endpoint_version}/pickup",
                    "missing_config_placeholders": missing_placeholders,
                    "payload": payload,
                }
            )
            return

        result = get_client().schedule_pickup(payload, version=endpoint_version)
        prn = result.get("prn") or result.get("PRN")
        print_success(f"UPS pickup scheduled: {prn or 'PRN unavailable'}")
        if table:
            _render_records([result], table=True, properties=None, empty="No response.", default_columns=SCHEDULE_COLUMNS)
        else:
            print_json(result)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
