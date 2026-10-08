"""Main entry point for Dataforseo CLI."""

import typer
from typing import List, Optional
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.data_cache import get_cache_hit
from cli_tools_shared.filters import apply_properties_filter, get_nested_value
from cli_tools_shared.output import command, print_info, print_json, print_table

from . import __version__
from .client import DEFAULT_LANGUAGE_CODE, DEFAULT_LOCATION_CODE, get_client
from .config import get_config

app = create_app(name="dataforseo", help="CLI interface for the DataForSEO API", version=__version__)
keywords_app = typer.Typer(help="Keyword research: search volume, difficulty, ideas", no_args_is_help=True)
account_app = typer.Typer(help="DataForSEO account balance and limits", no_args_is_help=True)

TABLE_OPTION = typer.Option(False, "--table", "-t", help="Display as table")
PROPERTIES_OPTION = typer.Option(
    None, "--properties", "-p", help="Comma-separated fields to include (dot-notation for nested fields)"
)
LOCATION_OPTION = typer.Option(DEFAULT_LOCATION_CODE, "--location-code", help="DataForSEO location code (2840 = United States)")
LANGUAGE_OPTION = typer.Option(DEFAULT_LANGUAGE_CODE, "--language-code", help="Language code (en = English)")

# table columns: (header, dot-path into the API record)
VOLUME_COLUMNS = [
    ("keyword", "keyword"),
    ("search_volume", "search_volume"),
    ("competition", "competition"),
    ("competition_index", "competition_index"),
    ("cpc", "cpc"),
]
DIFFICULTY_COLUMNS = [("keyword", "keyword"), ("keyword_difficulty", "keyword_difficulty")]
IDEAS_COLUMNS = [
    ("keyword", "keyword"),
    ("search_volume", "keyword_info.search_volume"),
    ("keyword_difficulty", "keyword_properties.keyword_difficulty"),
    ("cpc", "keyword_info.cpc"),
    ("intent", "search_intent_info.main_intent"),
]


def _report_cost(client) -> None:
    """Print the DataForSEO per-call cost to stderr (cached results cost nothing)."""
    if get_cache_hit():
        print_info("cost: $0 (cached result)")
    else:
        print_info(f"cost: ${client.last_cost}")


def _render(rows: List[dict], table: bool, properties: Optional[str], columns: List[tuple], empty: str) -> None:
    """JSON by default (full records); --properties projects fields; --table shows a flat view."""
    fields = [f.strip() for f in properties.split(",") if f.strip()] if properties else None
    if fields:
        rows = apply_properties_filter(rows, properties)
    if not table:
        print_json(rows)
        return
    if not rows:
        print_info(empty)
        return
    if fields:
        headers = fields
        view = rows
    else:
        headers = [name for name, _ in columns]
        view = [{name: get_nested_value(row, path) for name, path in columns} for row in rows]
    print_table(view, headers, [h.replace("_", " ").title() for h in headers])


@keywords_app.command("volume")
@command
def keywords_volume(
    keywords: List[str] = typer.Argument(..., help="One or more keywords (max 1000, 80 chars each)"),
    location_code: int = LOCATION_OPTION,
    language_code: str = LANGUAGE_OPTION,
    table: bool = TABLE_OPTION,
    properties: Optional[str] = PROPERTIES_OPTION,
):
    """Monthly Google search volume, competition, CPC and monthly trend (Google Ads, live)."""
    client = get_client()
    rows = client.search_volume(keywords, location_code, language_code)
    _report_cost(client)
    _render(rows, table, properties, VOLUME_COLUMNS, "No search volume data returned.")


@keywords_app.command("difficulty")
@command
def keywords_difficulty(
    keywords: List[str] = typer.Argument(..., help="One or more keywords (max 1000)"),
    location_code: int = LOCATION_OPTION,
    language_code: str = LANGUAGE_OPTION,
    table: bool = TABLE_OPTION,
    properties: Optional[str] = PROPERTIES_OPTION,
):
    """Keyword difficulty, 0-100 (DataForSEO Labs bulk keyword difficulty, live)."""
    client = get_client()
    rows = client.keyword_difficulty(keywords, location_code, language_code)
    _report_cost(client)
    _render(rows, table, properties, DIFFICULTY_COLUMNS, "No keyword difficulty data returned.")


@keywords_app.command("ideas")
@command
def keywords_ideas(
    seeds: List[str] = typer.Argument(..., help="One or more seed keywords (max 200)"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum keyword ideas (API max 1000)"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value on API fields, comma = AND (e.g. keyword_info.search_volume:gte:100)",
    ),
    order_by: Optional[str] = typer.Option(
        None, "--order-by", help="API sort rule, e.g. keyword_info.search_volume,desc (default: relevance)"
    ),
    location_code: int = LOCATION_OPTION,
    language_code: str = LANGUAGE_OPTION,
    table: bool = TABLE_OPTION,
    properties: Optional[str] = PROPERTIES_OPTION,
):
    """Related keyword ideas with volume, difficulty, CPC and search intent (DataForSEO Labs, live)."""
    client = get_client()
    rows = client.keyword_ideas(seeds, limit, filter, order_by, location_code, language_code)
    _report_cost(client)
    _render(rows, table, properties, IDEAS_COLUMNS, "No keyword ideas returned.")


@account_app.command("balance")
@command
def account_balance(table: bool = TABLE_OPTION):
    """Remaining account funds (free call)."""
    data = get_client().get_user_data()
    money = data["money"]
    row = {"login": data["login"], "balance": money["balance"], "total": money["total"]}
    if table:
        print_table([row], list(row), [k.title() for k in row])
    else:
        print_json(row)


app.add_typer(keywords_app, name="keywords")
app.add_typer(account_app, name="account")
app.add_typer(create_auth_app(get_config, tool_name="dataforseo"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
