"""Main entry point for Poshmark CLI."""

import typer
from typing import List, Optional
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import command, print_error, print_info, print_json, print_table

from . import __version__
from .client import ListingDetailBlocked, get_client
from .config import get_config

from cli_tools_shared.auth_commands import create_auth_app

COLUMNS = ["id", "title", "price", "size"]

# Source-CLI Sort Standard -> Poshmark ?sort_by= parameter values.
# Verified live against the Poshmark search "Sort By" dropdown (the dropdown's
# `items` attribute plus the per-value `--selected` menu label):
#   newest    -> added_desc    ("Just In")            natural = most recently listed first
#   price     -> price_asc     ("Price Low to High")  natural = low -> high
#   price -d  -> price_desc    ("Price High to Low")  reversed = high -> low
#   relevance -> relevance_v2  ("Relevance")          API relevance order; --desc rejected
# NOTE: Poshmark's `best_match` value is the "Just Shared" sort, NOT relevance;
# the option labeled "Relevance" is `relevance_v2`. Poshmark exposes no
# oldest-first (added_asc) sort, so `newest --desc` is rejected fail-fast.
SORT_MAP = {
    "newest": "added_desc",
    "price": "price_asc",
    "relevance": "relevance_v2",
}
# Fields whose natural direction can be reversed with --desc, mapped to the
# Poshmark sort_by value for the reversed direction.
SORT_DESC_MAP = {
    "price": "price_desc",
}


def _resolve_sort(sort: str, desc: bool = False) -> str:
    """Resolve --sort/--desc to a Poshmark ?sort_by= value (fail-fast, no fallback)."""
    key = sort.lower()
    if key not in SORT_MAP:
        valid = ", ".join(SORT_MAP)
        raise typer.BadParameter(f"Invalid --sort '{sort}'. Valid values: {valid}")
    if not desc:
        return SORT_MAP[key]
    if key not in SORT_DESC_MAP:
        raise typer.BadParameter(
            f"--desc is not supported with --sort {key}; Poshmark exposes no "
            f"reversed ordering for '{key}'."
        )
    return SORT_DESC_MAP[key]


app = create_app(name="poshmark", help="CLI interface for Poshmark", version=__version__)
listings_app = typer.Typer(help="Browse Poshmark listings", no_args_is_help=True)


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


def _list(fetch, filters, table, properties, empty) -> None:
    _validate(filters)
    rows = fetch()
    if filters:
        rows = apply_filters(rows, filters)
    _render(rows, table, properties, empty)


@listings_app.command("list")
@command
def listings_list(
    query: str = typer.Option("", "--query", help="Optional search query"),
    sort: str = typer.Option(
        "newest",
        "--sort",
        "-s",
        help="Sort field: 'newest' (default), 'price', or 'relevance'. Natural direction unless --desc.",
    ),
    desc: bool = typer.Option(
        False,
        "--desc",
        "-d",
        help="Reverse the sort field's natural direction (price low->high becomes high->low). Not valid with 'newest' or 'relevance'.",
    ),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List Poshmark listings, newest first by default."""
    sort_by = _resolve_sort(sort, desc)
    client = get_client()
    try:
        _list(lambda: client.search(query, limit, sort_by=sort_by), filter, table, properties, "No results found.")
    finally:
        client.close()


@listings_app.command("search")
@command
def listings_search(
    query: str = typer.Argument(..., help="Search query"),
    sort: str = typer.Option(
        "newest",
        "--sort",
        "-s",
        help="Sort field: 'newest' (default), 'price', or 'relevance'. Natural direction unless --desc.",
    ),
    desc: bool = typer.Option(
        False,
        "--desc",
        "-d",
        help="Reverse the sort field's natural direction (price low->high becomes high->low). Not valid with 'newest' or 'relevance'.",
    ),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Search Poshmark listings."""
    sort_by = _resolve_sort(sort, desc)
    client = get_client()
    try:
        _list(lambda: client.search(query, limit, sort_by=sort_by), None, table, properties, "No results found.")
    finally:
        client.close()


@listings_app.command("get")
@command
def listings_get(
    listing_id_or_url: str = typer.Argument(..., help="Poshmark listing ID or direct URL"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one Poshmark listing through the saved browser profile."""
    client = get_client()
    try:
        row = client.get_listing(listing_id_or_url)
    except ListingDetailBlocked as exc:
        print_json(exc.as_dict())
        raise typer.Exit(1)
    finally:
        client.close()

    fields = _property_fields(properties)
    if fields:
        row = apply_properties_filter([row], properties)[0]
    if not table:
        print_json(row)
        return
    if fields:
        print_table([row], fields, [field.replace("_", " ").title() for field in fields])
        return
    print_table(
        [{"field": key, "value": str(value)} for key, value in row.items()],
        ["field", "value"],
        ["Field", "Value"],
    )


app.add_typer(listings_app, name="listings")
app.add_typer(create_auth_app(get_config, tool_name="poshmark"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
