"""Main entry point for Mercari CLI."""

import typer
from typing import List, Optional
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
from .client import ClientError, get_client
from .config import get_config

# Default table columns. print_table auto-discovers the real columns from the
# data when these are absent, so no field is invented.
LIST_COLUMNS = ["id", "name", "price", "status", "created"]
# Validated present on every searchFacetQuery item (see README "Data source").
SEARCH_COLUMNS = ["id", "name", "price", "status", "categoryTitle"]

app = create_app(name="mercari", help="CLI interface for Mercari", version=__version__)
listings_app = typer.Typer(help="Read and search Mercari listings", no_args_is_help=True)


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


def _render_rows(
    rows: List[dict],
    table: bool,
    fields: Optional[List[str]],
    default_columns: List[str],
    empty_message: str,
) -> None:
    """Render a list of records as JSON (default) or a table."""
    if not table:
        print_json(rows)
        return
    if not rows:
        print_info(empty_message)
        return
    if fields:
        columns = fields
    else:
        # Prefer the validated default columns, but only those actually present
        # in the real records; fall back to auto-discovery (columns=None).
        columns = [c for c in default_columns if c in rows[0]] or None
    headers = [c.replace("_", " ").title() for c in columns] if columns else None
    print_table(rows, columns, headers)


@listings_app.command("list")
@command
def listings_list(
    status: str = typer.Option(
        "active", "--status", "-s", help="Listing status: active, inactive, or complete"
    ),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of listings"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter results (field:op:value)"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """List the authenticated seller's own listings for a status."""
    _validate(filter)
    client = get_client()
    try:
        rows = client.list_items(status=status, limit=limit)
    finally:
        client.close()

    if filter:
        rows = apply_filters(rows, filter)
    fields = _property_fields(properties)
    if fields:
        rows = apply_properties_filter(rows, properties)
    _render_rows(rows, table, fields, LIST_COLUMNS, f"No {status} listings found.")


@listings_app.command("search")
@command
def listings_search(
    keyword: str = typer.Argument(..., help="Search keyword"),
    status: Optional[str] = typer.Option(
        None, "--status", "-s", help="Item status: on_sale or sold"
    ),
    condition: Optional[str] = typer.Option(
        None, "--condition", "-c", help="Condition: new, like_new, good, fair, or poor"
    ),
    min_price: Optional[float] = typer.Option(
        None, "--min-price", help="Minimum price in US dollars"
    ),
    max_price: Optional[float] = typer.Option(
        None, "--max-price", help="Maximum price in US dollars"
    ),
    sort: str = typer.Option(
        "relevance", "--sort", help="Sort: relevance, price_asc, or price_desc"
    ),
    category_id: Optional[List[int]] = typer.Option(
        None, "--category-id", help="Filter by category id (repeatable; see result categoryId)"
    ),
    brand_id: Optional[List[int]] = typer.Option(
        None, "--brand-id", help="Filter by brand id (repeatable; see result brand.id)"
    ),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter results (field:op:value)"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """Search other sellers' public Mercari listings by keyword.

    Prices in --min-price/--max-price are US dollars; item prices in results
    are in cents (as Mercari returns them). Each result includes an `id` and
    canonical `url` so `mercari listings get <id>` composes with it.
    """
    _validate(filter)
    client = get_client()
    try:
        rows = client.search_items(
            keyword,
            limit=limit,
            status=status,
            condition=condition,
            min_price=min_price,
            max_price=max_price,
            sort=sort,
            category_ids=category_id,
            brand_ids=brand_id,
        )
    finally:
        client.close()

    if filter:
        rows = apply_filters(rows, filter)
    fields = _property_fields(properties)
    if fields:
        rows = apply_properties_filter(rows, properties)
    _render_rows(rows, table, fields, SEARCH_COLUMNS, f"No results for '{keyword}'.")


@listings_app.command("get")
@command
def listings_get(
    item_id: str = typer.Argument(..., help="Listing/item id (e.g. m12345678901) or URL"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """Get full detail for a single listing/item by id or URL."""
    client = get_client()
    try:
        row = client.get_item(item_id)
    finally:
        client.close()

    fields = _property_fields(properties)
    if fields:
        row = apply_properties_filter([row], properties)[0]

    if not table:
        print_json(row)
        return
    print_table(
        [{"field": key, "value": str(value)} for key, value in row.items()],
        ["field", "value"],
        ["Field", "Value"],
    )


app.add_typer(listings_app, name="listings")
app.add_typer(create_auth_app(get_config, tool_name="mercari"), name="auth")
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
