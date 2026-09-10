"""Marketplace search & item-detail commands for eBay CLI.

Two different backends, on purpose:

- ``search`` calls the SoldComps API (``api.sold-comps.com``), which sells the
  sold-comp and active-listing data eBay itself exposes to no public API. It
  needs the ``ebay-soldcomps-api-key`` secret and no browser at all.
- ``get`` and ``status`` still scrape the public ``/itm/<id>`` page through the
  shared stealth browser — SoldComps is a search product with no single-item
  lookup.

Commands:
- search: Search ACTIVE (live) or SOLD listings by keywords.
- get:    Fetch detail for a single active listing by item ID.
- status: Fetch availability without requiring fulfillment details.
"""
COMMAND_CREDENTIALS = {
    "search": ["no_auth"],
    "get": ["no_auth"],
    "status": ["no_auth"],
}

from typing import Optional

import typer

from ..browser_client import get_browser_client, BrowserError
from ..soldcomps_client import (
    get_soldcomps_client,
    resolve_sort_order,
    SoldCompsError,
    SEARCH_CONDITION_HELP,
    LISTING_FORMATS,
    LISTING_FORMAT_HELP,
    SEARCH_MAX_RESULTS,
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

# Table columns for sold-comp and active search results.
COMPLETED_TABLE_FIELDS = ["title", "price", "shipping_price", "status", "date_sold", "format", "bids"]
COMPLETED_TABLE_HEADERS = ["Title", "Price", "Shipping", "Status", "Date", "Format", "Bids"]
ACTIVE_TABLE_FIELDS = ["title", "price", "shipping_price", "status", "time_left", "format", "bids"]
ACTIVE_TABLE_HEADERS = ["Title", "Price", "Shipping", "Status", "Time Left", "Format", "Bids"]

# Table columns for item detail.
ITEM_TABLE_FIELDS = [
    "item_id", "title", "price", "currency", "format", "bids", "time_left",
    "shipping_price", "ships", "local_pickup", "item_location", "condition",
    "availability", "ended", "quantity", "seller",
]
ITEM_TABLE_HEADERS = [
    "Item ID", "Title", "Price", "Currency", "Format", "Bids", "Time Left",
    "Shipping", "Ships", "Pickup", "Location", "Condition",
    "Availability", "Ended", "Qty", "Seller",
]
STATUS_TABLE_FIELDS = ["item_id", "availability", "ended", "url"]
STATUS_TABLE_HEADERS = ["Item ID", "Availability", "Ended", "URL"]


@app.command("search")
@command
def listings_search(
    keywords: str = typer.Argument(..., help="Search keywords"),
    active: bool = typer.Option(
        False, "--active/--completed",
        help="Search ACTIVE (live, purchasable) listings instead of sold comps",
    ),
    listing_format: Optional[str] = typer.Option(
        None, "--format",
        help=LISTING_FORMAT_HELP + " (only applies with --active)",
    ),
    sold: bool = typer.Option(
        False, "--sold/--no-sold",
        help="Search completed SOLD listings (required unless --active is used)",
    ),
    min_price: Optional[float] = typer.Option(None, "--min-price", help="Minimum price filter"),
    max_price: Optional[float] = typer.Option(None, "--max-price", help="Maximum price filter"),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="eBay category ID"),
    condition: Optional[str] = typer.Option(
        None, "--condition",
        help=SEARCH_CONDITION_HELP,
    ),
    us_only: bool = typer.Option(
        False,
        "--us-only",
        help="Only show items located in the United States",
    ),
    sort: str = typer.Option(
        DEFAULT_SORT, "--sort", "-s",
        help=(
            "Sort field: " + ", ".join(VALID_SORT_FIELDS)
            + ". Default 'newest'. With --active, 'newest' = newly listed; for "
            "sold comps 'newest' = most recently ended/sold (there is no "
            "'newly listed' order for ended listings)."
        ),
    ),
    desc: bool = typer.Option(
        False, "--desc", "-d",
        help="Reverse the sort field's natural direction (only valid with --sort price).",
    ),
    limit: int = typer.Option(
        50,
        "--limit",
        "-l",
        help=(
            f"Maximum number of results (up to {SEARCH_MAX_RESULTS}); every 200 "
            "results cost one SoldComps request"
        ),
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter_expr: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., status:eq:active)"),
    properties: Optional[list[str]] = typer.Option(None, "--properties", "-p", help="Select fields to display"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Search eBay SOLD comps or ACTIVE listings via the SoldComps API.

    Pass --sold for completed, sold comps (the pricing signal) or --active for
    live, purchasable listings (BIN + auction) with current price, current bid,
    time-left, shipping, and item URL.

    Needs the SoldComps API key in the CLI-tools secret manager under
    'ebay-soldcomps-api-key'. No browser session and no eBay sign-in.

    Sold-comp searches are cached for the profile's CACHE_TTL, so repeating one
    costs no quota; pass the global --no-cache to force a fresh fetch. Active
    searches are never cached. `ebay quota` reports the plan usage recorded from
    the last response.

    Results are sorted newest-first by default. With --active, 'newest' orders
    by newly listed; for sold comps it orders by most recently ended/sold.

    Examples:

        ebay listings search "LEGO bulk lot" --active --format bin --limit 5

        ebay listings search "LEGO 75192" --sold --limit 5         # sold comps

        ebay listings search "LEGO 75192" --sold --us-only         # US items only

        ebay listings search "iPhone 15" --sold --sort price       # cheapest first

        ebay --no-cache listings search "LEGO 75192" --sold        # bypass cache
    """
    if active and sold:
        print_error("--sold applies to sold comps only; it cannot be combined with --active.")
        raise typer.Exit(1)

    if not active and not sold:
        print_error(
            "Unsold completed listings are no longer available: the SoldComps "
            "search API this CLI uses returns sold listings or active listings, "
            "nothing in between. Use --sold for completed sold comps or "
            "--active for live listings."
        )
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
        sort_order = resolve_sort_order(sort, desc, active=active)
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)

    try:
        client = get_soldcomps_client(profile=profile)

        try:
            if active:
                results = client.search_active(
                    keywords=keywords,
                    listing_format=listing_format,
                    min_price=min_price,
                    max_price=max_price,
                    category=category,
                    condition=condition,
                    us_only=us_only,
                    limit=limit,
                    sort_order=sort_order,
                )
            else:
                results = client.search_sold(
                    keywords=keywords,
                    min_price=min_price,
                    max_price=max_price,
                    category=category,
                    condition=condition,
                    us_only=us_only,
                    limit=limit,
                    sort_order=sort_order,
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

    except SoldCompsError as e:
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

    Fulfillment comes from eBay's own label rows: `ships` is true when the
    shipping row quotes a rate or delivery estimate, `local_pickup` is true
    when the pickup row is present, and `item_location` is the shipping row's
    "Located in:" origin. A page with neither row is an error, not "no
    fulfillment".

    Examples:

        ebay listings get 127992747834

        ebay listings get 127992747834 --table

        ebay listings get 127992747834 -p item_id,ships,local_pickup,item_location
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


@app.command("status")
@command
def listings_status(
    item_id: str = typer.Argument(..., help="eBay item ID (from a listing URL or search result)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[list[str]] = typer.Option(None, "--properties", "-p", help="Select fields to display"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Fetch availability for one eBay listing without fulfillment details.

    This command reads only item availability. It does not require shipping or
    local-pickup rows. Use `listings get` when you need full item detail.

    Examples:

        ebay listings status 127992747834

        ebay listings status 127992747834 -p item_id,ended
    """
    try:
        client = get_browser_client(profile=profile)

        try:
            data = client.get_item_status(item_id)
        finally:
            client.close()

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
                fields = STATUS_TABLE_FIELDS
                headers = STATUS_TABLE_HEADERS
            print_table([data], fields, headers)
        else:
            print_json(data)

    except BrowserError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))
