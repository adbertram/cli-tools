"""Author commands for Leanpub CLI."""
COMMAND_CREDENTIALS = {
    "stats": [
        "api_key"
    ]
}

from typing import List, Optional

import typer
from pydantic import BaseModel

from cli_tools_shared.filters import apply_properties_filter
from cli_tools_shared.output import handle_error, print_json, print_table

from .client import get_client


app = typer.Typer(help="Leanpub author commands", no_args_is_help=True)
stats_app = typer.Typer(help="Author revenue and royalty stats", no_args_is_help=True)
app.add_typer(stats_app, name="stats", help="Author revenue and royalty stats")

DEFAULT_STATS_COLUMNS = [
    "slug",
    "title",
    "total_revenue",
    "total_royalties",
    "total_copies_sold",
    "last_week_royalties",
]

DEFAULT_SUMMARY_COLUMNS = [
    "book_count",
    "total_revenue",
    "total_royalties",
    "total_copies_sold",
    "last_week_royalties",
]


def _to_dict(item):
    """Convert models to JSON-safe dictionaries."""
    if isinstance(item, BaseModel):
        return item.model_dump(mode="json")
    return item


def _apply_properties(items: list, properties: Optional[str]) -> list:
    """Apply dot-notation property selection to output rows."""
    rows = [_to_dict(item) for item in items]
    if properties:
        return apply_properties_filter(rows, properties)
    return rows


def _columns(properties: Optional[str], default_columns: List[str]) -> List[str]:
    """Return output columns for table rendering."""
    if properties:
        return [field.strip() for field in properties.split(",") if field.strip()]
    return default_columns


@stats_app.command("list")
def author_stats_list(
    slug: Optional[List[str]] = typer.Option(
        None,
        "--slug",
        "-s",
        help="Leanpub book slug. Repeat for multiple books. Defaults to BOOK_SLUGS.",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of books to query"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter results client-side: field:op:value",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include (supports dot-notation)",
    ),
):
    """List per-book Leanpub author revenue and royalty stats."""
    try:
        client = get_client()
        stats = client.list_author_stats(slugs=slug, limit=limit, filters=filter)
        output = _apply_properties(stats, properties)
        columns = _columns(properties, DEFAULT_STATS_COLUMNS)

        if table:
            print_table(output, columns, columns)
        else:
            print_json(output)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@stats_app.command("get")
def author_stats_get(
    slug: Optional[List[str]] = typer.Option(
        None,
        "--slug",
        "-s",
        help="Leanpub book slug. Repeat for multiple books. Defaults to BOOK_SLUGS.",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include (supports dot-notation)",
    ),
):
    """Get aggregated Leanpub author revenue and royalty stats."""
    try:
        client = get_client()
        stats = client.get_author_stats(slugs=slug)
        output = _apply_properties([stats], properties)[0]
        columns = _columns(properties, DEFAULT_SUMMARY_COLUMNS)

        if table:
            print_table([output], columns, columns)
        else:
            print_json(output)
    except Exception as e:
        raise typer.Exit(handle_error(e))
