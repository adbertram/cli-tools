import typer
from cli_tools_shared import create_app, create_auth_app, create_cache_app, run_app
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import command, print_error, print_info, print_json, print_table

from . import __version__
from .client import APPLICATION_FIELD_LABELS, get_client
from .config import get_config

COLUMNS = ["id", "title", "opportunity_type", "category", "posted_date", "is_new"]

app = create_app(
    name="pluralsight-author",
    help="CLI interface for Pluralsight Author opportunities",
    version=__version__,
)
opportunities_app = typer.Typer(help="List Pluralsight Author opportunities", no_args_is_help=True)
search_app = typer.Typer(help="Search Pluralsight Author opportunities", no_args_is_help=True)


def _property_fields(properties: str | None) -> list[str] | None:
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None


def _rows(items) -> list[dict]:
    return [item.model_dump() if hasattr(item, "model_dump") else item for item in items]


def _validate(filters: list[str] | None) -> None:
    if not filters:
        return
    try:
        validate_filters(filters)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


def _render(rows: list[dict], table: bool, properties: str | None, empty: str) -> None:
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
    rows = _rows(fetch())
    if filters:
        rows = apply_filters(rows, filters)
    _render(rows, table, properties, empty)


@opportunities_app.command("list")
@command
def list_opportunities(
    limit: int = typer.Option(1000, "--limit", "-l", help="Maximum number of opportunities"),
    filter: list[str] | None = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: str | None = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List opportunities from the Pluralsight Author opportunities page."""
    client = get_client()
    try:
        _list(lambda: client.list_opportunities(limit), filter, table, properties, "No opportunities found.")
    finally:
        client.close()


@opportunities_app.command("get")
@command
def get_opportunity(
    item_id: str = typer.Argument(..., help="Opportunity slug from `opportunities list`"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: str | None = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get a single opportunity by slug."""
    client = get_client()
    try:
        row = _rows([client.get_item(item_id)])
        fields = _property_fields(properties)
        if fields:
            _render(row, table, properties, "No opportunity found.")
        elif table:
            print_table(
                [{"field": key, "value": str(value)} for key, value in row[0].items()],
                ["field", "value"],
                ["Field", "Value"],
            )
        else:
            print_json(row[0])
    finally:
        client.close()


@opportunities_app.command("apply")
@command
def apply_opportunity(
    item_id: str = typer.Argument(..., help="Opportunity slug from `opportunities list`"),
    start_date: str = typer.Option(
        ...,
        "--start_date",
        help=APPLICATION_FIELD_LABELS["start_date"],
    ),
    estimated_completion_weeks: str = typer.Option(
        ...,
        "--estimated_completion_weeks",
        help=APPLICATION_FIELD_LABELS["estimated_completion_weeks"],
    ),
    experience: str = typer.Option(
        ...,
        "--experience",
        help=APPLICATION_FIELD_LABELS["experience"],
    ),
):
    """Submit a single opportunity application with explicit form field values."""
    client = get_client()
    try:
        print_json(
            client.apply(
                item_id,
                {
                    "start_date": start_date,
                    "estimated_completion_weeks": estimated_completion_weeks,
                    "experience": experience,
                },
            )
        )
    finally:
        client.close()


@search_app.command("query")
@command
def search_query(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: list[str] | None = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: str | None = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Search opportunities by title, type, or category."""
    client = get_client()
    try:
        _list(lambda: client.search(query, limit), filter, table, properties, "No results found.")
    finally:
        client.close()


app.add_typer(opportunities_app, name="opportunities")
app.add_typer(search_app, name="search")
app.add_typer(create_auth_app(get_config, tool_name="pluralsight-author"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    run_app(app)


if __name__ == "__main__":
    main()
