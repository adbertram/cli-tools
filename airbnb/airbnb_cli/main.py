"""Main entry point for Airbnb CLI."""

from __future__ import annotations

from datetime import date
from typing import Callable, List, Optional

import typer
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import command, print_error, print_info, print_json, print_table

from . import __version__
from .chrome_session import airbnb_auth_test, airbnb_chrome_login
from .client import (
    DEFAULT_CURRENCY,
    DEFAULT_LIST_LIMIT,
    DEFAULT_LOCALE,
    DEFAULT_RESERVATION_STATUS,
    DEFAULT_STAY_ADULTS,
    DEFAULT_STAY_CHILDREN,
    DEFAULT_STAY_INFANTS,
    DEFAULT_STAY_LIMIT,
    DEFAULT_STAY_PETS,
    AirbnbClient,
    get_client,
)
from .config import get_config

STAY_COLUMNS = ["id", "name", "title", "price_display", "rating"]
LISTING_COLUMNS = ["id", "name", "status"]
RESERVATION_COLUMNS = ["id", "confirmation_code", "start_date", "end_date", "status"]
MESSAGE_COLUMNS = ["id", "threadId", "type", "status"]
FILTER_HELP = "Filter results (field:op:value)"
PROPERTIES_HELP = "Comma-separated fields to include"
TABLE_HELP = "Display as table"

app = create_app(name="airbnb", help="Read-only Airbnb renter search and host data CLI", version=__version__)
stays_app = typer.Typer(help="Search available Airbnb stays", no_args_is_help=True)
listings_app = typer.Typer(help="Read Airbnb listings", no_args_is_help=True)
reservations_app = typer.Typer(help="Read Airbnb reservations", no_args_is_help=True)
messages_app = typer.Typer(help="Read Airbnb message threads", no_args_is_help=True)


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


def _validate_stay_search(
    destination: str,
    checkin: str,
    checkout: str,
    adults: int,
    children: int,
    infants: int,
    pets: int,
    limit: int,
) -> None:
    if not destination.strip():
        print_error("Destination is required.")
        raise typer.Exit(1)
    try:
        checkin_date = date.fromisoformat(checkin)
        checkout_date = date.fromisoformat(checkout)
    except ValueError:
        print_error("Dates must use YYYY-MM-DD format.")
        raise typer.Exit(1)
    if checkout_date <= checkin_date:
        print_error("Checkout must be after checkin.")
        raise typer.Exit(1)
    if adults < 1:
        print_error("Adults must be at least 1.")
        raise typer.Exit(1)
    for label, value in (("children", children), ("infants", infants), ("pets", pets)):
        if value < 0:
            print_error(f"{label} must be 0 or greater.")
            raise typer.Exit(1)
    if limit < 1:
        print_error("Limit must be at least 1.")
        raise typer.Exit(1)


def _render_rows(
    rows: List[dict],
    table: bool,
    properties: Optional[str],
    empty: str,
    columns: list[str],
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
    table_columns = fields or columns
    print_table(rows, table_columns, [column.replace("_", " ").title() for column in table_columns])


def _render_one(row: dict, table: bool, properties: Optional[str]) -> None:
    fields = _property_fields(properties)
    if fields:
        _render_rows([row], table, properties, "No record found.", fields)
    elif table:
        print_table(
            [{"field": key, "value": value} for key, value in row.items()],
            ["field", "value"],
            ["Field", "Value"],
        )
    else:
        print_json(row)


def _list(
    fetch: Callable[[], list[dict]],
    filters: Optional[List[str]],
    table: bool,
    properties: Optional[str],
    empty: str,
    columns: list[str],
) -> None:
    _validate(filters)
    rows = fetch()
    if filters:
        rows = apply_filters(rows, filters)
    _render_rows(rows, table, properties, empty, columns)


@listings_app.command("list")
@command
def list_listings(
    limit: int = typer.Option(DEFAULT_LIST_LIMIT, "--limit", "-l", help="Maximum number of listings"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help=FILTER_HELP),
    table: bool = typer.Option(False, "--table", "-t", help=TABLE_HELP),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help=PROPERTIES_HELP),
):
    """List Airbnb listings."""
    _list(
        lambda: get_client().list_listings(limit=limit),
        filter,
        table,
        properties,
        "No listings found.",
        LISTING_COLUMNS,
    )


@stays_app.command("search")
@command
def search_stays(
    destination: str = typer.Argument(..., help="Destination to search"),
    checkin: str = typer.Option(..., "--checkin", help="Check-in date, YYYY-MM-DD"),
    checkout: str = typer.Option(..., "--checkout", help="Checkout date, YYYY-MM-DD"),
    adults: int = typer.Option(DEFAULT_STAY_ADULTS, "--adults", help="Number of adult guests"),
    children: int = typer.Option(DEFAULT_STAY_CHILDREN, "--children", help="Number of child guests"),
    infants: int = typer.Option(DEFAULT_STAY_INFANTS, "--infants", help="Number of infant guests"),
    pets: int = typer.Option(DEFAULT_STAY_PETS, "--pets", help="Number of pets"),
    min_price: Optional[int] = typer.Option(None, "--min-price", help="Minimum nightly price"),
    max_price: Optional[int] = typer.Option(None, "--max-price", help="Maximum nightly price"),
    bedrooms: Optional[int] = typer.Option(None, "--bedrooms", help="Minimum bedrooms"),
    beds: Optional[int] = typer.Option(None, "--beds", help="Minimum beds"),
    bathrooms: Optional[int] = typer.Option(None, "--bathrooms", help="Minimum bathrooms"),
    room_type: Optional[List[str]] = typer.Option(None, "--room-type", help="Airbnb room type, repeatable"),
    property_type_id: Optional[List[str]] = typer.Option(None, "--property-type-id", help="Airbnb property type ID, repeatable"),
    currency: str = typer.Option(DEFAULT_CURRENCY, "--currency", help="Currency code"),
    locale: str = typer.Option(DEFAULT_LOCALE, "--locale", help="Locale code"),
    limit: int = typer.Option(DEFAULT_STAY_LIMIT, "--limit", "-l", help="Maximum number of stays"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help=FILTER_HELP),
    table: bool = typer.Option(False, "--table", "-t", help=TABLE_HELP),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help=PROPERTIES_HELP),
):
    """Search available Airbnb stays as a renter."""
    _validate_stay_search(destination, checkin, checkout, adults, children, infants, pets, limit)
    _list(
        lambda: AirbnbClient(require_credentials=False).search_stays(
            destination=destination,
            checkin=checkin,
            checkout=checkout,
            adults=adults,
            children=children,
            infants=infants,
            pets=pets,
            min_price=min_price,
            max_price=max_price,
            bedrooms=bedrooms,
            beds=beds,
            bathrooms=bathrooms,
            room_types=room_type,
            property_type_ids=property_type_id,
            currency=currency,
            locale=locale,
            limit=limit,
        ),
        filter,
        table,
        properties,
        "No stays found.",
        STAY_COLUMNS,
    )


@listings_app.command("get")
@command
def get_listing(
    listing_id: str = typer.Argument(..., help="Listing ID"),
    table: bool = typer.Option(False, "--table", "-t", help=TABLE_HELP),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help=PROPERTIES_HELP),
):
    """Get one Airbnb listing."""
    _render_one(get_client().get_listing(listing_id), table, properties)


@reservations_app.command("list")
@command
def list_reservations(
    limit: int = typer.Option(DEFAULT_LIST_LIMIT, "--limit", "-l", help="Maximum number of reservations"),
    date_min: Optional[str] = typer.Option(None, "--date-min", help="Minimum check-in date, YYYY-MM-DD"),
    status: str = typer.Option(
        DEFAULT_RESERVATION_STATUS,
        "--status",
        help="Comma-separated Airbnb reservation statuses",
    ),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help=FILTER_HELP),
    table: bool = typer.Option(False, "--table", "-t", help=TABLE_HELP),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help=PROPERTIES_HELP),
):
    """List Airbnb reservations."""
    _list(
        lambda: get_client().list_reservations(limit=limit, date_min=date_min, status=status),
        filter,
        table,
        properties,
        "No reservations found.",
        RESERVATION_COLUMNS,
    )


@reservations_app.command("get")
@command
def get_reservation(
    reservation_id: str = typer.Argument(..., help="Reservation ID or confirmation code"),
    table: bool = typer.Option(False, "--table", "-t", help=TABLE_HELP),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help=PROPERTIES_HELP),
):
    """Get one Airbnb reservation."""
    _render_one(get_client().get_reservation(reservation_id), table, properties)


@messages_app.command("list")
@command
def list_messages(
    limit: int = typer.Option(DEFAULT_LIST_LIMIT, "--limit", "-l", help="Maximum number of message threads"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help=FILTER_HELP),
    table: bool = typer.Option(False, "--table", "-t", help=TABLE_HELP),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help=PROPERTIES_HELP),
):
    """List Airbnb message threads."""
    _list(
        lambda: get_client().list_messages(limit=limit),
        filter,
        table,
        properties,
        "No message threads found.",
        MESSAGE_COLUMNS,
    )


@messages_app.command("get")
@command
def get_message_thread(
    thread_id: str = typer.Argument(..., help="Message thread ID"),
    table: bool = typer.Option(False, "--table", "-t", help=TABLE_HELP),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help=PROPERTIES_HELP),
):
    """Get one Airbnb message thread."""
    _render_one(get_client().get_message_thread(thread_id), table, properties)


app.add_typer(stays_app, name="stays")
app.add_typer(listings_app, name="listings")
app.add_typer(reservations_app, name="reservations")
app.add_typer(messages_app, name="messages")
app.add_typer(
    create_auth_app(
        get_config,
        tool_name="airbnb",
        login_handler=airbnb_chrome_login,
        test_handler=airbnb_auth_test,
    ),
    name="auth",
)
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
