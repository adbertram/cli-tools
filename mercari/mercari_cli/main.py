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

# Source-CLI Sort Standard -> Mercari search `sortBy` URL code.
# The Mercari search SPA translates a numeric ?sortBy= code into the
# searchFacetQuery criteria; each code bakes in its own direction (a sortOrder
# URL param is a no-op — verified live). Codes verified live against the fired
# criteria and the returned result order (top items' productQuery `created`
# timestamps were strictly descending for code 2):
#   newest    -> 2      created-time DESCENDING (newest listed first)
#   price     -> 3      price ascending  (low -> high)  [natural]
#   price -d  -> 4      price descending (high -> low)  [reversed]
#   relevance -> None   omit sortBy => best-match (codes 0/1 == best match)
# Mercari US search has NO oldest-first (created-ascending) code, so
# `newest --desc` is rejected fail-fast (no silent fallback to newest-first).
SORT_MAP = {
    "newest": 2,
    "price": 3,
    "relevance": None,
}
# Fields whose natural direction can be reversed with --desc, mapped to the
# Mercari sortBy code for the reversed direction.
SORT_DESC_MAP = {
    "price": 4,
}


def _resolve_sort(sort: str, desc: bool = False) -> Optional[int]:
    """Resolve --sort/--desc to a Mercari `sortBy` code (fail-fast, no fallback).

    Returns the numeric ``sortBy`` URL code, or ``None`` to omit the param
    (best-match/relevance). Raises ``typer.BadParameter`` for unknown fields,
    for ``relevance --desc``, and for ``newest --desc`` (Mercari US search has
    no oldest-first order).
    """
    key = sort.lower()
    if key not in SORT_MAP:
        valid = ", ".join(SORT_MAP)
        raise typer.BadParameter(f"Invalid --sort '{sort}'. Valid values: {valid}")
    if not desc:
        return SORT_MAP[key]
    if key in SORT_DESC_MAP:
        return SORT_DESC_MAP[key]
    if key == "newest":
        raise typer.BadParameter(
            "--desc is not supported with --sort newest: Mercari US search has no "
            "oldest-first order (only newest-first). Drop --desc for newest-first."
        )
    raise typer.BadParameter("--desc is not valid with --sort relevance.")

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
        None, "--status", help="Item status: on_sale or sold"
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
    sort_by = _resolve_sort(sort, desc)
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
            sort_by=sort_by,
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


@listings_app.command("get-many")
@command
def listings_get_many(
    item_ids: List[str] = typer.Argument(
        ..., help="Listing/item ids or URLs"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated item fields to include"
    ),
):
    """Get many listings through one public Mercari browser session."""
    client = get_client()
    try:
        rows = client.get_items(item_ids)
    finally:
        client.close()

    fields = _property_fields(properties)
    if fields:
        for row in rows:
            if row["status"] == "ok":
                row["item"] = apply_properties_filter([row["item"]], properties)[0]

    if not table:
        print_json(rows)
        return
    print_table(
        [
            {
                "item_id": row["item_id"],
                "status": row["status"],
                "item_status": row.get("item", {}).get("status"),
                "error_kind": row.get("error_kind"),
                "error": row.get("error"),
            }
            for row in rows
        ],
        ["item_id", "status", "item_status", "error_kind", "error"],
        ["Item Id", "Status", "Item Status", "Error Kind", "Error"],
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
