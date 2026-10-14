"""Main entry point for Clipster CLI."""

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



COLUMNS = ["id", "name", "status", "category", "web_url"]

app = create_app(name="clipster", help="Read Clipster's public clipping campaign catalog", version=__version__)
campaigns_app = typer.Typer(help="Read Clipster campaigns", no_args_is_help=True)


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


@campaigns_app.command("list")
@command
def list_campaigns(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of campaigns (reads as many pages as needed)"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List campaigns exactly as the API returns them, plus web_url."""
    _list(lambda: get_client().list_campaigns(limit), filter, table, properties, "No campaigns found.")


@campaigns_app.command("get")
@command
def get_campaign(
    campaign_id: str = typer.Argument(..., help="Campaign ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one campaign by ID."""
    row = get_client().get_campaign(campaign_id)
    fields = _property_fields(properties)
    if fields:
        _render([row], table, properties, "No campaign found.")
    elif table:
        print_table(
            [{"field": key, "value": str(value)} for key, value in row.items()],
            ["field", "value"],
            ["Field", "Value"],
        )
    else:
        print_json(row)


app.add_typer(campaigns_app, name="campaigns")

app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
