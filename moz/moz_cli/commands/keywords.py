"""Keywords commands for Moz CLI.

Commands for keyword research and analysis using Moz API.
"""
import typer
from typing import Optional, List

from rich.console import Console

from ..client import get_client, NoDataError
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import command, print_json, print_table, print_warning, print_error


# Note displayed above tables with volume data
VOLUME_NOTE = "[dim]Note: Volume is avg monthly searches over the last 12 months.[/dim]"
_console = Console()

METRIC_FIELDS = ["keyword", "volume", "difficulty", "ctr", "priority"]
METRIC_HEADERS = ["Keyword", "Volume", "Difficulty", "CTR", "Priority"]


app = typer.Typer(help="Keyword research and analysis", no_args_is_help=True)


@app.command("list")
@command
def keywords_list(
    keywords: Optional[str] = typer.Argument(
        None,
        help="Comma-separated list of keywords",
    ),
    keyword_option: Optional[str] = typer.Option(
        None,
        "--keyword",
        "-k",
        help="Comma-separated list of keywords",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum keywords to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., volume:gt:1000, keyword:contains:azure)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-P", help="Comma-separated fields to display"),
):
    """
    Get metrics for multiple keywords.

    Keywords Moz has no data for are named on stderr and omitted from the
    result; the keywords Moz did resolve are still returned.

    Examples:
        moz keywords list -k "seo,python,machine learning"
        moz keywords list -k "seo,python" --table
        moz keywords list -k "seo,python" --filter "volume:gt:1000"
        moz keywords list -k "seo,python" --properties "keyword,volume,difficulty"
    """
    if keywords and keyword_option and keywords != keyword_option:
        print_error("Pass keywords either positionally or with --keyword, not both")
        raise typer.Exit(1)

    keywords_value = keyword_option or keywords
    if not keywords_value:
        print_error("At least one keyword is required")
        raise typer.Exit(1)

    # Parse comma-separated keywords
    keyword_list = [kw.strip() for kw in keywords_value.split(",") if kw.strip()][:limit]
    if not keyword_list:
        print_error("At least one keyword is required")
        raise typer.Exit(1)

    client = get_client()

    # Moz has no bulk keyword-metrics action (probing
    # data.keyword.metrics.bulk.fetch returns "Action not found"), so each
    # keyword is resolved on its own request. A keyword Moz has no data for
    # answers with a 404 envelope; record that keyword as unresolved and keep
    # the metrics the other keywords returned. Every other failure (quota,
    # auth, transport) still aborts the command.
    results = []
    keywords_without_metrics = []
    for kw in keyword_list:
        try:
            results.append(client.get_keyword_metrics(kw).model_dump())
        except NoDataError:
            keywords_without_metrics.append(kw)

    if keywords_without_metrics:
        print_warning(
            f"Moz returned no metrics for {len(keywords_without_metrics)} of "
            f"{len(keyword_list)} keywords: "
            + ", ".join(f'"{kw}"' for kw in keywords_without_metrics)
        )

    results = apply_filters(results, filter, allowed_fields=METRIC_FIELDS)

    if properties:
        fields = [f.strip() for f in properties.split(",")]
        results = [{k: item.get(k) for k in fields} for item in results]
        headers = fields
    else:
        fields = METRIC_FIELDS
        headers = METRIC_HEADERS

    if table:
        if "volume" in fields:
            _console.print(VOLUME_NOTE)
        print_table(results, fields, headers)
    else:
        print_json(results)


@app.command("get")
@command
def keywords_get(
    keyword: str = typer.Argument(..., help="Keyword to look up"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get metrics for a keyword.

    Examples:
        moz keywords get "machine learning"
        moz keywords get "python tutorial" --table
    """
    client = get_client()
    try:
        metrics = client.get_keyword_metrics(keyword)
    except NoDataError:
        # A single-keyword lookup that resolves to nothing has no result to
        # return, so it exits non-zero like any other not-found lookup.
        print_error(f'Moz has no metrics for keyword "{keyword}"')
        raise typer.Exit(1)

    if table:
        _console.print(VOLUME_NOTE)
        print_table([metrics.model_dump()], METRIC_FIELDS, METRIC_HEADERS)
    else:
        print_json(metrics)


@app.command("suggestions")
@command
def keywords_suggestions(
    keyword: str = typer.Argument(..., help="Base keyword for suggestions"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum suggestions to return"),
):
    """
    Get related keyword suggestions.

    Examples:
        moz keywords suggestions "machine learning"
        moz keywords suggestions "python tutorial" --table --limit 20
    """
    client = get_client()
    suggestions = [s.model_dump() for s in client.get_keyword_suggestions(keyword)[:limit]]

    if table:
        _console.print(VOLUME_NOTE)
        print_table(
            suggestions,
            ["keyword", "volume", "difficulty"],
            ["Keyword", "Volume", "Difficulty"],
        )
    else:
        print_json(suggestions)


@app.command("intent")
@command
def keywords_intent(
    keyword: str = typer.Argument(..., help="Keyword to analyze"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get search intent for a keyword.

    Determines if a search is informational, navigational, commercial, or transactional.

    Examples:
        moz keywords intent "how to learn python"
        moz keywords intent "buy laptop" --table
    """
    client = get_client()
    intent = client.get_search_intent(keyword)

    if table:
        print_table(
            [intent.model_dump()],
            ["keyword", "intent_type", "confidence"],
            ["Keyword", "Intent Type", "Confidence"],
        )
    else:
        print_json(intent)


@app.command("ranking")
@command
def keywords_ranking(
    url: str = typer.Argument(..., help="URL to analyze"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum ranking keywords to return"),
):
    """
    Get keywords a URL ranks for.

    Examples:
        moz keywords ranking "https://example.com/blog/python"
        moz keywords ranking "https://example.com" --table --limit 20
    """
    client = get_client()
    keywords = [k.model_dump() for k in client.get_ranking_keywords(url)[:limit]]

    if table:
        _console.print(VOLUME_NOTE)
        print_table(
            keywords,
            ["keyword", "position", "volume", "difficulty"],
            ["Keyword", "Position", "Volume", "Difficulty"],
        )
    else:
        print_json(keywords)


COMMAND_CREDENTIALS = {
    "get": [
        "custom"
    ],
    "intent": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "ranking": [
        "custom"
    ],
    "suggestions": [
        "custom"
    ]
}
