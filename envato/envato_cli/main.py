"""Main entry point for Envato CLI."""

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
from .client import SORT_MAP, get_client, resolve_site, resolve_sort
from .config import get_config

COLUMNS = ["id", "title", "price", "number_of_sales", "rating", "rating_count", "updated_at"]

app = create_app(
    name="envato",
    help="CLI interface for the Envato Market API (CodeCanyon, ThemeForest, and other Envato sites)",
    version=__version__,
)


def _property_fields(properties: Optional[str]) -> Optional[List[str]]:
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None


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


@app.command("search")
@command
def search(
    term: str = typer.Argument(..., help="Search term, e.g. 'wordpress dropbox'"),
    site: str = typer.Option(
        "codecanyon",
        "--site",
        help="Envato site: codecanyon, themeforest, videohive, audiojungle, graphicriver, photodune, "
        "3docean (short name or domain such as codecanyon.net)",
    ),
    sort: str = typer.Option(
        "newest",
        "--sort",
        "-s",
        help=f"Sort field: {', '.join(SORT_MAP)}. newest/updated are newest-first; "
        "price/sales/rating are low-to-high; relevance is Envato's ranking.",
    ),
    desc: bool = typer.Option(
        False, "--desc", "-d", help="Reverse the sort field's natural direction (not valid with relevance)"
    ),
    page: int = typer.Option(1, "--page", "-P", min=1, max=60, help="Result page number (Envato allows 1-60)"),
    limit: int = typer.Option(20, "--limit", "-l", min=1, max=100, help="Results per page (1-100)"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Search Envato marketplace items by keyword.

    --site, --sort/--desc, --page, and --limit are sent to Envato's search API;
    --filter applies to the returned page.
    """
    sort_params = resolve_sort(sort, desc)
    if filter:
        try:
            validate_filters(filter)
        except FilterValidationError as exc:
            print_error(str(exc))
            raise typer.Exit(1)
    rows = get_client().search_items(term, resolve_site(site), limit, page, sort_params)
    if filter:
        rows = apply_filters(rows, filter)
    _render(rows, table, properties, f"No items found for '{term}'.")


@app.command("item")
@command
def item(
    item_id: int = typer.Argument(..., help="Envato item ID, e.g. 5529125"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get a single Envato marketplace item by ID."""
    row = get_client().get_item(str(item_id))
    if _property_fields(properties):
        row = apply_properties_filter([row], properties)[0]
    if table:
        print_table(
            [{"field": key, "value": str(value)} for key, value in row.items()],
            ["field", "value"],
            ["Field", "Value"],
        )
    else:
        print_json(row)


app.add_typer(create_auth_app(get_config, tool_name="envato"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
