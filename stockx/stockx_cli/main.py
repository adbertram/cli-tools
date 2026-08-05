"""Main entry point for StockX CLI."""

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
    CATEGORY_VALUES,
    COLOR_VALUES,
    DEFAULT_SORT,
    GENDER_VALUES,
    SORT_VALUES,
    ClientError,
    get_client,
    resolve_sort,
)
from .config import get_config

COLUMNS = ["id", "title", "brand", "productCategory", "url"]

app = create_app(
    name="stockx",
    help="Search and read StockX sneaker and streetwear market data",
    version=__version__,
)
products_app = typer.Typer(help="Search and read StockX products", no_args_is_help=True)


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


def _render_record(row: dict, table: bool, properties: Optional[str], empty: str) -> None:
    fields = _property_fields(properties)
    if fields:
        _render([row], table, properties, empty)
    elif table:
        print_table(
            [{"field": key, "value": str(value)} for key, value in row.items()],
            ["field", "value"],
            ["Field", "Value"],
        )
    else:
        print_json(row)


def _browse(
    query: Optional[str],
    limit: int,
    filter: Optional[List[str]],
    table: bool,
    properties: Optional[str],
    sort: str,
    desc: bool,
    brand: Optional[List[str]],
    gender: Optional[List[str]],
    category: Optional[List[str]],
    color: Optional[List[str]],
    activity: Optional[List[str]],
    below_retail: bool,
    xpress_ship: bool,
    min_price: Optional[float],
    max_price: Optional[float],
) -> None:
    """Shared body for `products search` and `products list`."""
    _validate(filter)
    sort_id = resolve_sort(sort, desc)
    client = get_client()
    try:
        rows = client.search_products(
            query=query,
            limit=limit,
            sort_id=sort_id,
            brand=brand,
            gender=gender,
            category=category,
            color=color,
            activity=activity,
            below_retail=below_retail,
            xpress_ship=xpress_ship,
            min_price=min_price,
            max_price=max_price,
        )
    finally:
        client.close()
    if filter:
        rows = apply_filters(rows, filter)
    _render(rows, table, properties, "No products found.")


_LIMIT = typer.Option(40, "--limit", "-l", help="Maximum number of products (merged across pages)")
_FILTER = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)")
_TABLE = typer.Option(False, "--table", "-t", help="Display as table")
_PROPERTIES = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include")
_SORT = typer.Option(DEFAULT_SORT, "--sort", "-s", help=f"Sort field: {', '.join(SORT_VALUES)}")
_DESC = typer.Option(False, "--desc", "-d", help="Reverse the sort field's natural direction")
_BRAND = typer.Option(None, "--brand", "-b", help="Brand slug, repeatable (e.g. nike, adidas)")
_GENDER = typer.Option(None, "--gender", "-g", help=f"Gender, repeatable: {', '.join(GENDER_VALUES)}")
_CATEGORY = typer.Option(None, "--category", "-c", help=f"Category, repeatable: {', '.join(CATEGORY_VALUES)}")
_COLOR = typer.Option(None, "--color", help=f"Color, repeatable: {', '.join(COLOR_VALUES)}")
_ACTIVITY = typer.Option(None, "--activity", help="Activity slug, repeatable (e.g. basketball, running)")
_BELOW_RETAIL = typer.Option(False, "--below-retail", help="Only products asking below retail")
_XPRESS_SHIP = typer.Option(False, "--xpress-ship", help="Only products eligible for Xpress Ship")
_MIN_PRICE = typer.Option(None, "--min-price", help="Minimum lowest ask in US dollars (needs --max-price)")
_MAX_PRICE = typer.Option(None, "--max-price", help="Maximum lowest ask in US dollars (needs --min-price)")


@products_app.command("search")
@command
def products_search(
    query: str = typer.Argument(..., help="Search keywords"),
    limit: int = _LIMIT,
    filter: Optional[List[str]] = _FILTER,
    table: bool = _TABLE,
    properties: Optional[str] = _PROPERTIES,
    sort: str = _SORT,
    desc: bool = _DESC,
    brand: Optional[List[str]] = _BRAND,
    gender: Optional[List[str]] = _GENDER,
    category: Optional[List[str]] = _CATEGORY,
    color: Optional[List[str]] = _COLOR,
    activity: Optional[List[str]] = _ACTIVITY,
    below_retail: bool = _BELOW_RETAIL,
    xpress_ship: bool = _XPRESS_SHIP,
    min_price: Optional[float] = _MIN_PRICE,
    max_price: Optional[float] = _MAX_PRICE,
):
    """Search the StockX catalog by keyword."""
    _browse(
        query, limit, filter, table, properties, sort, desc, brand, gender,
        category, color, activity, below_retail, xpress_ship, min_price, max_price,
    )


@products_app.command("list")
@command
def products_list(
    limit: int = _LIMIT,
    filter: Optional[List[str]] = _FILTER,
    table: bool = _TABLE,
    properties: Optional[str] = _PROPERTIES,
    sort: str = _SORT,
    desc: bool = _DESC,
    brand: Optional[List[str]] = _BRAND,
    gender: Optional[List[str]] = _GENDER,
    category: Optional[List[str]] = _CATEGORY,
    color: Optional[List[str]] = _COLOR,
    activity: Optional[List[str]] = _ACTIVITY,
    below_retail: bool = _BELOW_RETAIL,
    xpress_ship: bool = _XPRESS_SHIP,
    min_price: Optional[float] = _MIN_PRICE,
    max_price: Optional[float] = _MAX_PRICE,
):
    """Browse the StockX catalog with no keyword."""
    _browse(
        None, limit, filter, table, properties, sort, desc, brand, gender,
        category, color, activity, below_retail, xpress_ship, min_price, max_price,
    )


@products_app.command("get")
@command
def products_get(
    product: str = typer.Argument(..., help="Product url key or stockx.com product URL"),
    table: bool = _TABLE,
    properties: Optional[str] = _PROPERTIES,
):
    """Get the catalog record for one product."""
    client = get_client()
    try:
        row = client.get_product(product)
    finally:
        client.close()
    _render_record(row, table, properties, "No product found.")


@products_app.command("market")
@command
def products_market(
    product: str = typer.Argument(..., help="Product url key or stockx.com product URL"),
    table: bool = _TABLE,
    properties: Optional[str] = _PROPERTIES,
):
    """Get live market data (asks, bids, sales) for one product."""
    client = get_client()
    try:
        row = client.get_market(product)
    finally:
        client.close()
    _render_record(row, table, properties, "No market data found.")


app.add_typer(products_app, name="products")
app.add_typer(create_auth_app(get_config, tool_name="stockx"), name="auth")
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
