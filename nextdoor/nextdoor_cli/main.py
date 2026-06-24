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
from .client import get_client
from .config import get_config

from cli_tools_shared.auth_commands import create_auth_app

COLUMNS = ["id", "name", "status"]

app = create_app(name="nextdoor", help="CLI interface for Nextdoor API", version=__version__)
items_app = typer.Typer(help="Manage nextdoor items", no_args_is_help=True)


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


@app.command("feed")
@command
def feed(
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum number of items"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """View personalized feed."""
    _list(lambda: get_client().get_feed(limit), filter, table, properties, "No feed items found.")


@app.command("me")
@command
def me(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """View current user profile."""
    row = get_client().get_me()
    fields = _property_fields(properties)
    if fields:
        _render([row], table, properties, "No user found.")
    elif table:
        print_table(
            [{"field": key, "value": str(value)} for key, value in row.items()],
            ["field", "value"],
            ["Field", "Value"],
        )
    else:
        print_json(row)


@app.command("notifications")
@command
def notifications(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """View unread notifications and badges."""
    row = get_client().get_notifications()
    fields = _property_fields(properties)
    if fields:
        _render([row], table, properties, "No notifications found.")
    elif table:
        print_table(
            [{"field": key, "value": str(value)} for key, value in row.items()],
            ["field", "value"],
            ["Field", "Value"],
        )
    else:
        print_json(row)


@app.command("search")
@command
def search(
    query: str = typer.Argument(..., help="Search query"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Search Nextdoor suggestions."""
    _list(lambda: get_client().search(query), filter, table, properties, "No search results found.")
app.add_typer(create_auth_app(get_config, tool_name="nextdoor"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
