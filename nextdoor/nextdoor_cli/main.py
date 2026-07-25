"""Main entry point for Nextdoor CLI."""

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
from .client import (
    CLASSIFIED_COLUMNS,
    CLASSIFIED_SORT_MAP,
    FEED_COLUMNS,
    FEED_SORT_MAP,
    NOTIFICATION_COLUMNS,
    SEARCH_COLUMNS,
    get_client,
)
from .config import get_config

from cli_tools_shared.auth_commands import create_auth_app

# Table columns come from client.py, where each normalize function owns both
# the record shape and its column order, so the two can never drift.

app = create_app(name="nextdoor", help="CLI interface for Nextdoor API", version=__version__)


def _property_fields(properties: Optional[str]) -> Optional[List[str]]:
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None


def _resolve_sort(sort_map: dict, sort: str, desc: bool) -> str:
    """Validate ``--sort``/``--desc`` and return the matching server sort value.

    Implements the Source-CLI Sort Standard for both listing surfaces:
    ``newest`` (the default, natural direction = newest-first) maps to the
    source's chronological server sort; ``relevance`` maps to its algorithmic
    order. Unknown values fail fast with a clear error (no silent fallback).
    ``relevance`` has no reverse direction, so ``--desc`` with it is rejected.
    For ``newest``, ``--desc`` (oldest-first) is applied by the caller as a
    client-side reversal of the fetched page.
    """
    key = sort.lower()
    if key not in sort_map:
        valid = ", ".join(sort_map)
        raise typer.BadParameter(f"Invalid --sort '{sort}'. Valid values: {valid}.")
    if key == "relevance" and desc:
        raise typer.BadParameter(
            "--desc is not supported with '--sort relevance' (relevance order has no reverse)."
        )
    return sort_map[key]


def _validate(filters: Optional[List[str]]) -> None:
    if not filters:
        return
    try:
        validate_filters(filters)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


def _fetch(fetch):
    """Run ``fetch(client)`` and guarantee the client is closed afterward."""
    client = get_client()
    try:
        return fetch(client)
    finally:
        client.close()


def _render(rows: List[dict], table: bool, properties: Optional[str], columns, empty: str) -> None:
    fields = _property_fields(properties)
    if fields:
        rows = apply_properties_filter(rows, properties)
    if not table:
        print_json(rows)
        return
    if not rows:
        print_info(empty)
        return
    selected = list(fields or columns)
    print_table(rows, selected, [column.replace("_", " ").title() for column in selected])


def _list(fetch, filters, table, properties, columns, empty) -> None:
    _validate(filters)
    rows = _fetch(fetch)
    if filters:
        rows = apply_filters(rows, filters)
    _render(rows, table, properties, columns, empty)


def _table_value(value) -> str:
    """Render one record value for the field/value table.

    Scalars render as-is. Nested objects/lists are summarized compactly so the
    table stays readable (a deeply nested user profile would otherwise dump a
    wall of text). The full structure is always available via default JSON
    output.
    """
    if isinstance(value, dict):
        for key in ("displayName", "text", "name", "title", "url"):
            inner = value.get(key)
            if isinstance(inner, str) and inner:
                return inner
        return f"{{{len(value)} fields}}"
    if isinstance(value, list):
        return f"[{len(value)} items]"
    return str(value)


def _render_record(fetch, table: bool, properties: Optional[str], empty: str) -> None:
    row = _fetch(fetch)
    fields = _property_fields(properties)
    if fields:
        _render([row], table, properties, fields, empty)
    elif table:
        print_table(
            [{"field": key, "value": _table_value(value)} for key, value in row.items()],
            ["field", "value"],
            ["Field", "Value"],
        )
    else:
        print_json(row)


@app.command("feed")
@command
def feed(
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum number of items"),
    sort: str = typer.Option(
        "newest",
        "--sort",
        "-s",
        help="Sort field: 'newest' (default; most recent first, server-side) or 'relevance' (algorithmic feed).",
    ),
    desc: bool = typer.Option(
        False,
        "--desc",
        "-d",
        help="Reverse the sort's natural order (newest -> oldest-first, over the fetched page).",
    ),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """View the feed (default: newest first)."""
    sort_order = _resolve_sort(FEED_SORT_MAP, sort, desc)

    def fetch(client):
        rows = client.get_feed(limit, sort_order=sort_order)
        return list(reversed(rows)) if desc else rows

    _list(fetch, filter, table, properties, FEED_COLUMNS, "No feed items found.")


@app.command("me")
@command
def me(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """View current user profile."""
    _render_record(lambda client: client.get_me(), table, properties, "No user found.")


@app.command("notifications")
@command
def notifications(
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of items"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """View unread notifications and badges."""
    _list(
        lambda client: client.get_notifications()[:limit],
        filter,
        table,
        properties,
        NOTIFICATION_COLUMNS,
        "No notifications found.",
    )


@app.command("search")
@command
def search(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(25, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Search Nextdoor content (listings, neighbors, events, businesses, posts).

    Results are grouped by Nextdoor's own relevance ranking; the operation
    accepts no sort or paging arguments, so there is no --sort and --limit caps
    the returned rows.
    """
    _list(
        lambda client: client.search(query, limit),
        filter,
        table,
        properties,
        SEARCH_COLUMNS,
        "No search results found.",
    )


classifieds_app = typer.Typer(help="Browse the For Sale & Free classifieds")


@classifieds_app.command("list")
@command
def classifieds_list(
    query: str = typer.Argument("", help="Optional keyword to search listings (default: browse all)"),
    limit: int = typer.Option(25, "--limit", "-l", help="Maximum number of listings"),
    sort: str = typer.Option(
        "newest",
        "--sort",
        "-s",
        help="Sort field: 'newest' (default; most recent first, server-side) or 'relevance' (Nextdoor's 'Most Relevant' order).",
    ),
    desc: bool = typer.Option(
        False,
        "--desc",
        "-d",
        help="Reverse the sort's natural order (newest -> oldest-first, over the fetched pages).",
    ),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List For Sale & Free listings with their direct listing URLs."""
    sort_order = _resolve_sort(CLASSIFIED_SORT_MAP, sort, desc)

    def fetch(client):
        rows = client.list_classifieds(query, limit, sort_order=sort_order)
        return list(reversed(rows)) if desc else rows

    _list(fetch, filter, table, properties, CLASSIFIED_COLUMNS, "No listings found.")


@classifieds_app.command("get")
@command
def classifieds_get(
    classified_id: str = typer.Argument(..., help="Listing ID (the UUID in the listing URL)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one For Sale & Free listing with its full description and details."""
    _render_record(
        lambda client: client.get_classified(classified_id),
        table,
        properties,
        "No listing found.",
    )


app.add_typer(classifieds_app, name="classifieds")
app.add_typer(create_auth_app(get_config, tool_name="nextdoor"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
