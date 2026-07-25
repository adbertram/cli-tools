"""Main entry point for America's Thrift Supply CLI."""

import typer
from typing import List, Optional
from cli_tools_shared import create_app, run_app
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


PRODUCT_COLUMNS = ["id", "handle", "title", "product_type", "price_usd", "available", "variant_count", "url"]
COLLECTION_COLUMNS = ["id", "handle", "title", "products_count", "url"]

# Canonical Source-CLI sort vocabulary for this fixed-price Shopify catalog.
# The storefront's Shopify JSON endpoints ignore ?sort_by=, so ordering is
# applied client-side on the returned fields (see _sort_products).
SORT_FIELDS = ("newest", "price")

app = create_app(
    name="americasthriftsupply",
    help="CLI interface for the America's Thrift Supply public Shopify storefront catalog",
    version=__version__,
)
products_app = typer.Typer(help="Browse the product catalog", no_args_is_help=True)
collections_app = typer.Typer(help="Browse storefront collections (categories)", no_args_is_help=True)


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


def _resolve_sort(sort: str) -> str:
    """Validate --sort against the canonical vocabulary (fail-fast, no silent fallback)."""
    key = sort.lower()
    if key not in SORT_FIELDS:
        valid = ", ".join(SORT_FIELDS)
        raise typer.BadParameter(f"Invalid --sort '{sort}'. Valid values: {valid}")
    return key


def _sort_products(rows: List[dict], sort_field: str, desc: bool) -> List[dict]:
    """Sort normalized product rows client-side.

    The storefront's Shopify JSON endpoints ignore ?sort_by=, so ordering is
    applied here on the returned fields. ``newest`` natural direction is
    newest-listed first (``created_at`` descending); ``price`` natural direction
    is low -> high. ``--desc`` reverses whichever field's natural direction.
    Products without a resolved price always trail the priced rows.
    """
    if sort_field == "newest":
        return sorted(rows, key=lambda row: row["created_at"], reverse=not desc)
    priced = [row for row in rows if row["price_usd"] is not None]
    unpriced = [row for row in rows if row["price_usd"] is None]
    priced.sort(key=lambda row: row["price_usd"], reverse=desc)
    return priced + unpriced


def _render_list(rows: List[dict], table: bool, properties: Optional[str], columns: List[str], empty: str) -> None:
    fields = _property_fields(properties)
    if fields:
        rows = apply_properties_filter(rows, properties)
    if not table:
        print_json(rows)
        return
    if not rows:
        print_info(empty)
        return
    columns = fields or columns
    print_table(rows, columns, [column.replace("_", " ").title() for column in columns])


def _render_detail(row: dict, table: bool, properties: Optional[str]) -> None:
    fields = _property_fields(properties)
    if fields:
        row = apply_properties_filter([row], properties)[0]
    if table:
        print_table(
            [{"field": key, "value": str(value)} for key, value in row.items()],
            ["field", "value"],
            ["Field", "Value"],
        )
        return
    print_json(row)


@products_app.command("list")
@command
def list_products(
    sort: str = typer.Option(
        "newest",
        "--sort",
        "-s",
        help="Sort field: 'newest' (default) or 'price'. Natural direction unless --desc.",
    ),
    desc: bool = typer.Option(
        False,
        "--desc",
        "-d",
        help="Reverse the sort field's natural direction (newest->oldest; price low->high becomes high->low).",
    ),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of products to return"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter results (field:op:value), e.g. 'title:ilike:%mystery%' or 'price_usd:lte:30'",
    ),
    collection: Optional[str] = typer.Option(
        None,
        "--collection",
        "-c",
        help="Restrict to one collection handle (server-side), e.g. 'mystery-box' or 'lego'",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List (and search via --filter) products in the catalog.

    The storefront has no full-text search JSON endpoint, so text search is done
    client-side with --filter, e.g.:

        americasthriftsupply products list --filter "title:ilike:%lego%"

    The Shopify JSON endpoints ignore ?sort_by=, so --sort/--desc order the
    returned result set (up to --limit) client-side. Default 'newest' returns
    the newest-listed products first.
    """
    sort_field = _resolve_sort(sort)
    _validate(filter)
    try:
        rows = get_client().list_products(limit=limit, collection=collection)
    except ClientError as exc:
        print_error(str(exc))
        raise typer.Exit(1)
    if filter:
        rows = apply_filters(rows, filter)
    rows = _sort_products(rows, sort_field, desc)
    _render_list(rows, table, properties, PRODUCT_COLUMNS, "No products found.")


@products_app.command("get")
@command
def get_product(
    handle: str = typer.Argument(..., help="Product handle, e.g. 'lego-mystery-box'"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get full detail (price, live availability, variants, images) for one product."""
    try:
        row = get_client().get_product(handle)
    except ClientError as exc:
        print_error(str(exc))
        raise typer.Exit(1)
    _render_detail(row, table, properties)


@collections_app.command("list")
@command
def list_collections(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of collections to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List storefront collections (categories), e.g. 'mystery-box', 'lego'."""
    _validate(filter)
    try:
        rows = get_client().list_collections(limit=limit)
    except ClientError as exc:
        print_error(str(exc))
        raise typer.Exit(1)
    if filter:
        rows = apply_filters(rows, filter)
    _render_list(rows, table, properties, COLLECTION_COLUMNS, "No collections found.")


@collections_app.command("get")
@command
def get_collection(
    handle: str = typer.Argument(..., help="Collection handle, e.g. 'mystery-box'"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get detail for one collection by handle."""
    try:
        row = get_client().get_collection(handle)
    except ClientError as exc:
        print_error(str(exc))
        raise typer.Exit(1)
    _render_detail(row, table, properties)


app.add_typer(products_app, name="products")
app.add_typer(collections_app, name="collections")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
