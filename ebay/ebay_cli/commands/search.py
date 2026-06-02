"""Marketplace search commands for eBay CLI.

Searches eBay completed/sold listings via browser automation.
Uses Playwright to scrape search results since eBay restricts
completed listing search to Terapeak partners (no public API).

Commands:
- search: Search completed/sold listings by keywords
"""
COMMAND_CREDENTIALS = {
    "search": ["no_auth"],
}

from typing import Optional

import typer

from ..browser_client import get_browser_client, BrowserError
from cli_tools_shared.output import (
    print_json,
    print_table,
    handle_error,
    print_error,
)
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError
from ..properties import validate_and_filter_properties, PropertyValidationError


app = typer.Typer(help="Search eBay marketplace listings")

# Table columns for search results
SEARCH_TABLE_FIELDS = ["title", "price", "shipping_price", "status", "date_sold", "format", "bids"]
SEARCH_TABLE_HEADERS = ["Title", "Price", "Shipping", "Status", "Date", "Format", "Bids"]


@app.command("search")
def listings_search(
    keywords: str = typer.Argument(..., help="Search keywords"),
    sold: bool = typer.Option(False, "--sold/--no-sold", help="Only show sold items (default: all completed)"),
    min_price: Optional[float] = typer.Option(None, "--min-price", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    max_price: Optional[float] = typer.Option(None, "--max-price", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="eBay category ID"),
    condition: Optional[str] = typer.Option(
        None, "--condition",
        help="Item condition (new, open_box, refurbished, used, for_parts, or eBay condition ID)"
    ),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of results"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter_expr: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[list[str]] = typer.Option(None, "--properties", "-p", help="Select fields to display"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Search eBay completed/sold listings.

    Searches eBay marketplace for completed listings using browser automation.
    Returns sold and unsold completed listings by default. Use --sold to filter
    to only sold items.

    Examples:

        ebay listings search "LEGO 75192" --sold --limit 5

        ebay listings search "LEGO bulk" --table

        ebay listings search "iPhone 15" --sold --min-price 500 --max-price 1000
    """
    try:
        client = get_browser_client(profile=profile)

        try:
            results = client.search_completed(
                keywords=keywords,
                sold_only=sold,
                min_price=min_price,
                max_price=max_price,
                category=category,
                condition=condition,
                limit=limit,
            )
        finally:
            client.close()

        # Convert to dicts for output
        data = [r.to_dict() for r in results]

        # Apply client-side filters
        if filter_expr:
            try:
                parsed = validate_filters(filter_expr, list(data[0].keys()) if data else [])
                data = apply_filters(data, parsed)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply property selection
        if properties:
            try:
                data = validate_and_filter_properties(data, properties)
            except PropertyValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        if table:
            if properties:
                fields = properties
                headers = properties
            else:
                fields = SEARCH_TABLE_FIELDS
                headers = SEARCH_TABLE_HEADERS
            print_table(data, fields, headers)
        else:
            print_json(data)

    except BrowserError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))
