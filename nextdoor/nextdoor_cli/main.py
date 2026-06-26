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
    FEED_COLUMNS,
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
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """View personalized feed."""
    _list(lambda client: client.get_feed(limit), filter, table, properties, FEED_COLUMNS, "No feed items found.")


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
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Search Nextdoor suggestions."""
    _list(
        lambda client: client.search(query),
        filter,
        table,
        properties,
        SEARCH_COLUMNS,
        "No search results found.",
    )


app.add_typer(create_auth_app(get_config, tool_name="nextdoor"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
