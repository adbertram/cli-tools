"""Main entry point for Vinted CLI."""

import typer
from typing import List, Optional
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.filters import (
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import command, print_info, print_json, print_table

from . import __version__
from .client import (
    DEFAULT_SORT,
    VALID_CONDITIONS,
    VALID_SORT_FIELDS,
    get_client,
    resolve_condition_ids,
    resolve_order,
)
from .config import get_config

TABLE_COLUMNS = ["id", "title", "brand", "price", "currency", "condition"]

app = create_app(name="vinted", help="CLI interface for Vinted marketplace", version=__version__)
listings_app = typer.Typer(help="Search Vinted marketplace listings", no_args_is_help=True)


def _requested_fields(properties: Optional[str]) -> Optional[List[str]]:
    """Parsed --properties field names, or None when none were requested."""
    if not properties:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None


def _render(rows: List[dict], table: bool, properties: Optional[str], empty: str) -> None:
    projected = apply_properties_filter(rows, properties)
    if not table:
        print_json(projected)
        return
    if not projected:
        print_info(empty)
        return
    fields = _requested_fields(properties)
    if fields:
        # The user named the fields, so show every one. print_table drops
        # columns past its sixth by default, which would lose data silently.
        print_table(projected, fields, fields, max_columns=0)
        return
    print_table(projected, TABLE_COLUMNS, [column.replace("_", " ").title() for column in TABLE_COLUMNS])


@listings_app.command("search")
@command
def listings_search(
    query: str = typer.Argument(..., help="Search keywords"),
    sort: str = typer.Option(
        DEFAULT_SORT, "--sort", "-s",
        help=(
            "Sort field: " + ", ".join(VALID_SORT_FIELDS)
            + ". Default 'newest' (most recently listed first)."
        ),
    ),
    desc: bool = typer.Option(
        False, "--desc", "-d",
        help="Reverse the sort field's natural direction (only valid with --sort price).",
    ),
    min_price: Optional[float] = typer.Option(None, "--min-price", help="Minimum price"),
    max_price: Optional[float] = typer.Option(None, "--max-price", help="Maximum price"),
    currency: Optional[str] = typer.Option(None, "--currency", help="Currency code for the price range (e.g. USD)"),
    condition: Optional[List[str]] = typer.Option(
        None, "--condition", "-c",
        help="Item condition, repeatable: " + ", ".join(VALID_CONDITIONS),
    ),
    catalog_id: Optional[str] = typer.Option(None, "--catalog-id", help="Vinted catalog (category) IDs, comma-separated"),
    brand_id: Optional[str] = typer.Option(None, "--brand-id", help="Vinted brand IDs, comma-separated"),
    size_id: Optional[str] = typer.Option(None, "--size-id", help="Vinted size IDs, comma-separated"),
    color_id: Optional[str] = typer.Option(None, "--color-id", help="Vinted color IDs, comma-separated"),
    include_shipping: bool = typer.Option(
        False, "--include-shipping",
        help="Add the shipping figures. One paced item page request per listing, so it is slow.",
    ),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f",
        help="Filter results: field:op:value (e.g., brand:eq:LEGO, title:contains:bulk)",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Search Vinted marketplace listings.

    Results are newest-listed first by default. Price, condition, catalog,
    brand, size, and color are sent to Vinted as search parameters, so the
    limit applies to matching listings only.

    Examples:

        vinted listings search "lego bulk lot" --limit 10 --table

        vinted listings search "lego" --sort price --max-price 25 --currency USD

        vinted listings search "lego" --condition new-with-tags --condition good

        vinted listings search "lego" --properties "id,title,price,url"

        vinted listings search "lego" --limit 10 --include-shipping
    """
    # Validate the filter before the network call. @command turns any raise
    # here into the same stderr message and exit code 1.
    if filter:
        validate_filters(filter)

    rows = get_client().search_listings(
        query=query,
        limit=limit,
        order=resolve_order(sort, desc),
        min_price=min_price,
        max_price=max_price,
        currency=currency,
        status_ids=resolve_condition_ids(condition),
        catalog_ids=catalog_id,
        brand_ids=brand_id,
        size_ids=size_id,
        color_ids=color_id,
    )
    if filter:
        rows = apply_filters(rows, filter)
    if include_shipping and rows:
        # Say what this costs before it runs, so a long wait is never a surprise.
        client = get_client()
        print_info(
            f"Shipping needs one item page per listing, for {len(rows)} listings. "
            f"The rate limiter keeps at least {client.limiter.interval:.1f}s between "
            "requests."
        )
        rows = client.add_shipping(rows)
    _render(rows, table, properties, "No listings found.")


@listings_app.command("get")
@command
def listings_get(
    item_id: str = typer.Argument(..., help="Vinted listing ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one Vinted listing by its ID.

    Adds the description, category, color, total price, and shipping that
    catalog search omits. It does not carry the seller login or the view count.

    Examples:

        vinted listings get 9571854910

        vinted listings get 9571854910 --table

        vinted listings get 9571854910 --properties "id,title,description"
    """
    row = get_client().get_listing(item_id)

    fields = _requested_fields(properties)
    if fields:
        row = apply_properties_filter([row], properties)[0]

    if not table:
        # One listing is always one JSON object, with or without --properties.
        print_json(row)
        return
    if fields:
        print_table([row], fields, fields, max_columns=0)
        return
    print_table(
        [{"field": key, "value": str(value)} for key, value in row.items()],
        ["field", "value"],
        ["Field", "Value"],
    )


app.add_typer(
    create_auth_app(get_config, tool_name="vinted"),
    name="auth",
    help="Manage the Vinted browser session",
)
app.add_typer(listings_app, name="listings")

app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
