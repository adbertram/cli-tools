"""Main entry point for Depop CLI."""

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
from .client import get_client, resolve_sort
from .config import get_config

# Validated present on every search result object (see client.py docstring).
SEARCH_COLUMNS = ["id", "brand_name", "price", "currency", "condition", "gender", "category", "url"]

app = create_app(name="depop", help="CLI interface for the Depop resale marketplace", version=__version__)


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
    empty_message: str,
) -> None:
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
    query: str = typer.Argument(..., help="Search keyword, e.g. 'nike jacket'"),
    price_min: Optional[float] = typer.Option(None, "--price-min", help="Minimum price in US dollars"),
    price_max: Optional[float] = typer.Option(None, "--price-max", help="Maximum price in US dollars"),
    condition: Optional[List[str]] = typer.Option(
        None,
        "--condition",
        "-c",
        help="Condition (repeatable): brand_new, used_like_new, used_excellent, used_good, used_fair",
    ),
    gender: Optional[str] = typer.Option(None, "--gender", help="Gender: male, female, or unisex"),
    category: Optional[str] = typer.Option(
        None, "--category", help="Category group slug, e.g. coats-jackets, tops, dresses (see a result's 'category' field)"
    ),
    sort: str = typer.Option(
        "relevance",
        "--sort",
        "-s",
        help="Sort field: price (natural low->high) or relevance (default). "
        "Depop's search API has no usable chronological 'newest' sort.",
    ),
    desc: bool = typer.Option(
        False,
        "--desc",
        "-d",
        help="Reverse the sort field's natural direction (price -> high->low). Not valid with relevance.",
    ),
    limit: int = typer.Option(24, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Search public Depop listings by keyword.

    Every filter (price, condition, gender, category, sort) is sent to
    Depop's own search API, and `--limit` drives the requested page size /
    cursor pagination rather than truncating a larger fetched list.
    """
    sort_param = resolve_sort(sort, desc)
    _validate(filter)
    client = get_client()
    try:
        rows = client.search_items(
            query,
            limit=limit,
            price_min=price_min,
            price_max=price_max,
            condition=condition,
            gender=gender,
            category=category,
            sort_param=sort_param,
        )
    finally:
        client.close()

    if filter:
        rows = apply_filters(rows, filter)
    fields = _property_fields(properties)
    if fields:
        rows = apply_properties_filter(rows, properties)
    _render_rows(rows, table, fields, f"No results for '{query}'.")


app.add_typer(create_auth_app(get_config, tool_name="depop"), name="auth")
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
