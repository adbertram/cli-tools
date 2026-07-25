"""Marketplace search & item-detail commands for eBay CLI.

Searches eBay listings via the shared stealth browser (Playwright/CDP), since
eBay restricts completed-listing search to Terapeak partners and exposes no
public API for active-listing discovery:

Commands:
- search: Search ACTIVE (live) or completed/sold listings by keywords.
- get:    Fetch detail for a single active listing by item ID.
"""
COMMAND_CREDENTIALS = {
    "search": ["no_auth"],
    "get": ["no_auth"],
}

from typing import Optional

import typer

from ..browser_client import (
    get_browser_client,
    resolve_sop,
    BrowserError,
    SEARCH_CONDITION_HELP,
    LISTING_FORMATS,
    LISTING_FORMAT_HELP,
    DEFAULT_SORT,
    VALID_SORT_FIELDS,
)
from cli_tools_shared.output import (
    command,
    print_json,
    print_table,
    handle_error,
    print_error,
)
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError
from ..properties import validate_and_filter_properties, PropertyValidationError


app = typer.Typer(help="Search eBay marketplace listings")

# Table columns for completed-comps and active search results.
COMPLETED_TABLE_FIELDS = ["title", "price", "shipping_price", "status", "date_sold", "format", "bids"]
COMPLETED_TABLE_HEADERS = ["Title", "Price", "Shipping", "Status", "Date", "Format", "Bids"]
ACTIVE_TABLE_FIELDS = ["title", "price", "shipping_price", "status", "time_left", "format", "bids"]
ACTIVE_TABLE_HEADERS = ["Title", "Price", "Shipping", "Status", "Time Left", "Format", "Bids"]

# Table columns for item detail.
ITEM_TABLE_FIELDS = [
    "item_id", "title", "price", "currency", "format", "bids", "time_left",
    "shipping_price", "condition", "availability", "ended", "quantity", "seller",
]
ITEM_TABLE_HEADERS = [
    "Item ID", "Title", "Price", "Currency", "Format", "Bids", "Time Left",
    "Shipping", "Condition", "Availability", "Ended", "Qty", "Seller",
]


@app.command("search")
@command
def listings_search(
    keywords: str = typer.Argument(..., help="Search keywords"),
    active: bool = typer.Option(
        False, "--active/--completed",
        help="Search ACTIVE (live, purchasable) listings instead of completed/sold comps",
    ),
    listing_format: Optional[str] = typer.Option(
        None, "--format",
        help=LISTING_FORMAT_HELP + " (only applies with --active)",
    ),
    sold: bool = typer.Option(False, "--sold/--no-sold", help="Completed search only: only show sold items"),
    min_price: Optional[float] = typer.Option(None, "--min-price", help="Minimum price filter"),
    max_price: Optional[float] = typer.Option(None, "--max-price", help="Maximum price filter"),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="eBay category ID"),
    condition: Optional[str] = typer.Option(
        None, "--condition",
        help=SEARCH_CONDITION_HELP,
    ),
    sort: str = typer.Option(
        DEFAULT_SORT, "--sort", "-s",
        help=(
            "Sort field: " + ", ".join(VALID_SORT_FIELDS)
            + ". Default 'newest'. With --active, 'newest' = newly listed; for "
            "completed comps 'newest' = most recently ended/sold (eBay has no "
            "'newly listed' order for ended listings)."
        ),
    ),
    desc: bool = typer.Option(
        False, "--desc", "-d",
        help="Reverse the sort field's natural direction (only valid with --sort price).",
    ),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of results"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter_expr: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., status:eq:active)"),
    properties: Optional[list[str]] = typer.Option(None, "--properties", "-p", help="Select fields to display"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Search eBay ACTIVE or completed/sold listings.

    By default searches COMPLETED listings (sold + unsold comps). Pass --active
    to search live, purchasable listings (BIN + auction) with current price,
    current bid, time-left, shipping, and item URL.

    Results are sorted newest-first by default. With --active, 'newest' orders
    by newly listed; for completed comps it orders by most recently ended/sold.

    Examples:

        ebay listings search "LEGO bulk lot" --active --format bin --limit 5

        ebay listings search "LEGO 75192" --active --format auction --sort ending

        ebay listings search "LEGO 75192" --sold --limit 5        # completed comps

        ebay listings search "iPhone 15" --sort price             # cheapest first
    """
    if active and sold:
        print_error("--sold applies to completed comps only; it cannot be combined with --active.")
        raise typer.Exit(1)

    if listing_format is not None:
        listing_format = listing_format.lower()
        if listing_format not in LISTING_FORMATS:
            print_error(
                f"Invalid --format '{listing_format}'. Valid values: {', '.join(LISTING_FORMATS)}"
            )
            raise typer.Exit(1)
        if not active:
            print_error("--format only applies with --active.")
            raise typer.Exit(1)

    try:
        sop = resolve_sop(sort, desc, active=active)
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)

    try:
        client = get_browser_client(profile=profile)

        try:
            if active:
                results = client.search_active(
                    keywords=keywords,
                    listing_format=listing_format,
                    min_price=min_price,
                    max_price=max_price,
                    category=category,
                    condition=condition,
                    limit=limit,
                    sop=sop,
                )
            else:
                results = client.search_completed(
                    keywords=keywords,
                    sold_only=sold,
                    min_price=min_price,
                    max_price=max_price,
                    category=category,
                    condition=condition,
                    limit=limit,
                    sop=sop,
                )
        finally:
            client.close()

        data = [r.to_dict() for r in results]

        if filter_expr:
            try:
                parsed = validate_filters(filter_expr, list(data[0].keys()) if data else [])
                data = apply_filters(data, parsed)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # --properties accepts repeated flags (-p a -p b) or a comma list
        # (-p a,b); validate_and_filter_properties wants one comma string.
        prop_str = ",".join(properties) if properties else None
        if prop_str:
            try:
                data = validate_and_filter_properties(data, prop_str)
            except PropertyValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        if table:
            if prop_str:
                fields = [p.strip() for p in prop_str.split(",")]
                headers = fields
            elif active:
                fields = ACTIVE_TABLE_FIELDS
                headers = ACTIVE_TABLE_HEADERS
            else:
                fields = COMPLETED_TABLE_FIELDS
                headers = COMPLETED_TABLE_HEADERS
            print_table(data, fields, headers)
        else:
            print_json(data)

    except BrowserError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def listings_get(
    item_id: str = typer.Argument(..., help="eBay item ID (from a listing URL or search result)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[list[str]] = typer.Option(None, "--properties", "-p", help="Select fields to display"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Fetch detail for a single active eBay listing by item ID.

    Scrapes the public /itm/<id> page (schema.org Product JSON-LD + DOM) for
    price, currency, condition, availability, shipping, current bid, and
    time-left.

    Examples:

        ebay listings get 127992747834

        ebay listings get 127992747834 --table
    """
    try:
        client = get_browser_client(profile=profile)

        try:
            detail = client.get_item(item_id)
        finally:
            client.close()

        data = detail.to_dict()

        prop_str = ",".join(properties) if properties else None
        if prop_str:
            try:
                data = validate_and_filter_properties([data], prop_str)[0]
            except PropertyValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        if table:
            if prop_str:
                fields = [p.strip() for p in prop_str.split(",")]
                headers = fields
            else:
                fields = ITEM_TABLE_FIELDS
                headers = ITEM_TABLE_HEADERS
            print_table([data], fields, headers)
        else:
            print_json(data)

    except BrowserError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))
