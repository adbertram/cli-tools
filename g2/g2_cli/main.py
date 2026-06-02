"""Main entry point for G2 CLI."""

import typer
from typing import Callable, List, Optional
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import command, print_error, print_info, print_json, print_table

from . import __version__
from .commands import products, reviews
from .client import get_client
from .config import get_config

PRODUCT_COLUMNS = [
    "id",
    "name",
    "slug",
    "product_type",
    "domain",
    "star_rating",
]
REVIEW_COLUMNS = [
    "id",
    "product_name",
    "product_slug",
    "star_rating",
    "title",
    "submitted_at",
]

app = create_app(name="g2", help="CLI interface for G2 API", version=__version__)
products_app = typer.Typer(help="Find and inspect G2 products", no_args_is_help=True)
reviews_app = typer.Typer(help="Find and inspect G2 product reviews", no_args_is_help=True)


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


def _render(rows: List[dict], table: bool, properties: Optional[str], empty: str, columns: List[str]) -> None:
    fields = _property_fields(properties)
    if fields:
        rows = apply_properties_filter(rows, properties)
    if not table:
        print_json(rows)
        return
    if not rows:
        print_info(empty)
        return
    visible_columns = fields or columns
    print_table(rows, visible_columns, [column.replace("_", " ").title() for column in visible_columns])


def _render_single(row: dict, table: bool, properties: Optional[str], empty: str, columns: List[str]) -> None:
    fields = _property_fields(properties)
    if fields:
        _render([row], table, properties, empty, columns)
        return
    if table:
        print_table(
            [{"field": key, "value": str(value)} for key, value in row.items()],
            ["field", "value"],
            ["Field", "Value"],
        )
        return
    print_json(row)


def _list(fetch: Callable[[], List[dict]], filters, table, properties, empty, columns: List[str]) -> None:
    _validate(filters)
    rows = fetch()
    if filters:
        rows = apply_filters(rows, filters)
    _render(rows, table, properties, empty, columns)


def _stars_option(stars: Optional[List[int]]) -> List[int]:
    if not stars:
        return [1, 2]
    invalid = [star for star in stars if star < 1 or star > 5]
    if invalid:
        print_error("Star ratings must be integers between 1 and 5.")
        raise typer.Exit(1)
    return stars


@products_app.command("list")
@command
def list_products(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of products"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List G2 products."""
    _list(lambda: get_client().list_products(limit), filter, table, properties, "No products found.", PRODUCT_COLUMNS)


@products_app.command("get")
@command
def get_product(
    slug: str = typer.Argument(..., help="Product slug"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get a product by slug."""
    _render_single(
        get_client().get_product(slug),
        table,
        properties,
        "No product found.",
        PRODUCT_COLUMNS,
    )


@products_app.command("search")
@command
def search_products(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Search G2 products using the official API search filter."""
    _list(
        lambda: get_client().search_products(query, limit),
        filter,
        table,
        properties,
        "No products found.",
        PRODUCT_COLUMNS,
    )


@reviews_app.command("list")
@command
def list_reviews(
    product_slug: str = typer.Argument(..., help="Product slug"),
    stars: Optional[List[int]] = typer.Option(None, "--stars", help="Repeatable star ratings to include"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of reviews"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List reviews for a product slug."""
    selected_stars = _stars_option(stars)
    _list(
        lambda: get_client().list_reviews(product_slug, stars=selected_stars, limit=limit),
        filter,
        table,
        properties,
        "No reviews found.",
        REVIEW_COLUMNS,
    )


@reviews_app.command("get")
@command
def get_review(
    review_id: str = typer.Argument(..., help="Review ID, survey response ID, or review slug"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one accessible review by ID, survey response ID, or review slug."""
    _render_single(
        get_client().get_review(review_id),
        table,
        properties,
        "No review found.",
        REVIEW_COLUMNS,
    )


@reviews_app.command("search")
@command
def search_reviews(
    product_slug: str = typer.Argument(..., help="Product slug"),
    query: str = typer.Argument(..., help="Search query"),
    stars: Optional[List[int]] = typer.Option(None, "--stars", help="Repeatable star ratings to include"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of reviews"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Search accessible reviews for a product slug by normalized output fields."""
    selected_stars = _stars_option(stars)
    _list(
        lambda: get_client().search_reviews(product_slug, query, stars=selected_stars, limit=limit),
        filter,
        table,
        properties,
        "No reviews found.",
        REVIEW_COLUMNS,
    )


products.app = products_app
reviews.app = reviews_app
register_commands(app, get_config, products, name="products", help="Find and inspect G2 products")
register_commands(app, get_config, reviews, name="reviews", help="Find and inspect G2 product reviews")
app.add_typer(create_auth_app(get_config, tool_name="g2"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
