"""Main entry point for OfferUp CLI."""

from typing import List, Optional

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
from .client import (
    CONDITION_VALUES,
    DEFAULT_SORT,
    RADIUS_VALUES,
    SORT_VALUES,
    ClientError,
    get_client,
    resolve_sort,
)
from .config import get_config

COLUMNS = ["id", "title", "price", "locationName", "url"]

app = create_app(
    name="offerup",
    help="Search and read OfferUp local marketplace listings",
    version=__version__,
)
listings_app = typer.Typer(help="Search and read OfferUp listings", no_args_is_help=True)


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


def _render(rows: List[dict], table: bool, properties: Optional[str], empty: str) -> None:
    fields = _property_fields(properties)
    if fields:
        rows = apply_properties_filter(rows, properties)
    if not table:
        print_json(rows)
        return
    if not rows:
        print_info(empty)
        return
    columns = fields or COLUMNS
    print_table(rows, columns, [column.replace("_", " ").title() for column in columns])


def _feed(
    query: Optional[str],
    limit: int,
    filter: Optional[List[str]],
    table: bool,
    properties: Optional[str],
    sort: str,
    desc: bool,
    condition: Optional[List[str]],
    min_price: Optional[float],
    max_price: Optional[float],
    radius: Optional[str],
    latitude: Optional[float],
    longitude: Optional[float],
    empty: str,
) -> None:
    """Shared body for `listings search` and `listings list`."""
    _validate(filter)
    sort_token = resolve_sort(sort, desc)
    client = get_client()
    try:
        rows = client.search_listings(
            query=query,
            limit=limit,
            sort_token=sort_token,
            condition=condition,
            min_price=min_price,
            max_price=max_price,
            radius=radius,
            latitude=latitude,
            longitude=longitude,
        )
    finally:
        client.close()
    if filter:
        rows = apply_filters(rows, filter)
    _render(rows, table, properties, empty)


_LIMIT = typer.Option(50, "--limit", "-l", help="Maximum number of listings (merged across pages)")
_FILTER = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)")
_TABLE = typer.Option(False, "--table", "-t", help="Display as table")
_PROPERTIES = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include")
_SORT = typer.Option(DEFAULT_SORT, "--sort", "-s", help=f"Sort field: {', '.join(SORT_VALUES)}")
_DESC = typer.Option(False, "--desc", "-d", help="Reverse the sort field's natural direction")
_CONDITION = typer.Option(None, "--condition", "-c", help=f"Item condition, repeatable: {', '.join(CONDITION_VALUES)}")
_MIN_PRICE = typer.Option(None, "--min-price", help="Minimum price in US dollars")
_MAX_PRICE = typer.Option(None, "--max-price", help="Maximum price in US dollars")
_RADIUS = typer.Option(None, "--radius", "-r", help=f"Search radius in miles: {', '.join(RADIUS_VALUES)}")
_LATITUDE = typer.Option(None, "--latitude", help="Search latitude in decimal degrees")
_LONGITUDE = typer.Option(None, "--longitude", help="Search longitude in decimal degrees")


@listings_app.command("search")
@command
def listings_search(
    query: str = typer.Argument(..., help="Search keywords"),
    limit: int = _LIMIT,
    filter: Optional[List[str]] = _FILTER,
    table: bool = _TABLE,
    properties: Optional[str] = _PROPERTIES,
    sort: str = _SORT,
    desc: bool = _DESC,
    condition: Optional[List[str]] = _CONDITION,
    min_price: Optional[float] = _MIN_PRICE,
    max_price: Optional[float] = _MAX_PRICE,
    radius: Optional[str] = _RADIUS,
    latitude: Optional[float] = _LATITUDE,
    longitude: Optional[float] = _LONGITUDE,
):
    """Search public OfferUp listings by keyword."""
    _feed(
        query, limit, filter, table, properties, sort, desc, condition,
        min_price, max_price, radius, latitude, longitude,
        "No listings found.",
    )


@listings_app.command("list")
@command
def listings_list(
    limit: int = _LIMIT,
    filter: Optional[List[str]] = _FILTER,
    table: bool = _TABLE,
    properties: Optional[str] = _PROPERTIES,
    sort: str = _SORT,
    desc: bool = _DESC,
    condition: Optional[List[str]] = _CONDITION,
    min_price: Optional[float] = _MIN_PRICE,
    max_price: Optional[float] = _MAX_PRICE,
    radius: Optional[str] = _RADIUS,
    latitude: Optional[float] = _LATITUDE,
    longitude: Optional[float] = _LONGITUDE,
):
    """List the local OfferUp feed with no keyword."""
    _feed(
        None, limit, filter, table, properties, sort, desc, condition,
        min_price, max_price, radius, latitude, longitude,
        "No listings found.",
    )


@listings_app.command("get")
@command
def listings_get(
    item: str = typer.Argument(..., help="Listing id or offerup.com item URL"),
    table: bool = _TABLE,
    properties: Optional[str] = _PROPERTIES,
):
    """Get the full detail record for one listing."""
    client = get_client()
    try:
        row = client.get_listing(item)
    finally:
        client.close()
    fields = _property_fields(properties)
    if fields:
        _render([row], table, properties, "No listing found.")
    elif table:
        print_table(
            [{"field": key, "value": str(value)} for key, value in row.items()],
            ["field", "value"],
            ["Field", "Value"],
        )
    else:
        print_json(row)


app.add_typer(listings_app, name="listings")
app.add_typer(create_auth_app(get_config, tool_name="offerup"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    try:
        run_app(app)
    except ClientError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


if __name__ == "__main__":
    main()
