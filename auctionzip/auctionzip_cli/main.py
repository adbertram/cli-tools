"""Main entry point for the AuctionZip CLI."""

from typing import List, Optional

import typer
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import command, print_error, print_info, print_json, print_table

from . import __version__
from .client import get_client
from .config import get_config

# Default table columns for search results (fields validated present per parser).
SEARCH_COLUMNS = [
    "ref",
    "lot_number",
    "title",
    "auction_house",
    "current_bid",
    "bids",
    "time_remaining",
    "close_time",
    "url",
]

app = create_app(
    name="auctionzip",
    help="Search AuctionZip auctions and read lot detail (Cloudflare-cleared browser session).",
    version=__version__,
)


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


def _render_rows(rows: List[dict], table: bool, fields: Optional[List[str]], empty_message: str) -> None:
    if not table:
        print_json(rows)
        return
    if not rows:
        print_info(empty_message)
        return
    columns = fields or [c for c in SEARCH_COLUMNS if c in rows[0]] or None
    headers = [c.replace("_", " ").title() for c in columns] if columns else None
    print_table(rows, columns, headers)


@app.command("search")
@command
def search(
    query: str = typer.Argument(..., help="Search keyword, e.g. 'lego' or 'lego star wars'"),
    limit: int = typer.Option(24, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Search public AuctionZip lots by keyword.

    Returns lot summaries (ref, lot number, title, auction house, current bid,
    bid count, close time / time remaining, estimate, and the lot URL). Bids are
    point-in-time; pass --no-cache for a fresh read.
    """
    _validate(filter)
    client = get_client()
    try:
        rows = client.search(query, limit=limit)
    finally:
        client.close()

    if filter:
        rows = apply_filters(rows, filter)
    fields = _property_fields(properties)
    if fields:
        rows = apply_properties_filter(rows, properties)
    _render_rows(rows, table, fields, f"No results for '{query}'.")


@app.command("get")
@command
def get(
    lot: str = typer.Argument(..., help="Lot URL, slug_ref, or lot reference (from a search result)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get full detail for a single AuctionZip lot.

    Returns current bid, bid count, next minimum bid, buyer's premium, status,
    auction type, close time, location, accepted payment, shipping/pickup terms,
    and conditions of sale. Bid/status are point-in-time; pass --no-cache for a
    fresh read.
    """
    client = get_client()
    try:
        row = client.get_item(lot)
    finally:
        client.close()

    fields = _property_fields(properties)
    if fields:
        row = apply_properties_filter([row], properties)[0]
    if not table:
        print_json(row)
        return
    print_table(
        [{"field": key, "value": "" if value is None else str(value)} for key, value in row.items()],
        ["field", "value"],
        ["Field", "Value"],
    )


app.add_typer(create_auth_app(get_config, tool_name="auctionzip"), name="auth")
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
