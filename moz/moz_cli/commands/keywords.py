"""Keywords commands for Moz CLI.

Commands for keyword research and analysis using Moz API.
"""
import typer
from typing import Optional, List

from rich.console import Console

from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, handle_error, print_success, print_error


# Note displayed above tables with volume data
VOLUME_NOTE = "[dim]Note: Volume is avg monthly searches over the last 12 months.[/dim]"
_console = Console()


app = typer.Typer(help="Keyword research and analysis", no_args_is_help=True)


@app.command("list")
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
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-P", help="Comma-separated fields to display"),
):
    """
    Get metrics for multiple keywords.

    Examples:
        moz keywords list -k "seo,python,machine learning"
        moz keywords list -k "seo,python" --table
        moz keywords list -k "seo,python" --filter "volume:gt:1000"
        moz keywords list -k "seo,python" --properties "keyword,volume,difficulty"
    """
    try:
        if keywords and keyword_option and keywords != keyword_option:
            print_error("Pass keywords either positionally or with --keyword, not both")
            raise typer.Exit(1)

        keywords_value = keyword_option or keywords
        if not keywords_value:
            print_error("At least one keyword is required")
            raise typer.Exit(1)

        # Parse comma-separated keywords
        keyword_list = [kw.strip() for kw in keywords_value.split(",") if kw.strip()]
        if not keyword_list:
            print_error("At least one keyword is required")
            raise typer.Exit(1)

        client = get_client()

        # Get metrics for each keyword
        results = []
        for kw in keyword_list[:limit]:
            metrics = client.get_keyword_metrics(kw)
            results.append(metrics)

        # Apply client-side filtering if specified
        if filter:
            from cli_tools_shared.filters import apply_filters
            results = apply_filters(results, filter)

        # Extract specific properties if requested
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            results_dicts = [r.model_dump() for r in results]
            filtered_results = []
            for item in results_dicts:
                filtered_item = {k: item.get(k) for k in fields}
                filtered_results.append(filtered_item)

            if table:
                # Show note if volume is in the selected fields
                if "volume" in fields:
                    _console.print(VOLUME_NOTE)
                print_table(filtered_results, fields, fields)
            else:
                print_json(filtered_results)
        else:
            if table:
                _console.print(VOLUME_NOTE)
                data = [r.model_dump() for r in results]
                fields = ["keyword", "volume", "difficulty", "ctr", "priority"]
                headers = ["Keyword", "Volume", "Difficulty", "CTR", "Priority"]
                print_table(data, fields, headers)
            else:
                print_json([r.model_dump() for r in results])

    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
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
    try:
        client = get_client()
        metrics = client.get_keyword_metrics(keyword)

        if table:
            _console.print(VOLUME_NOTE)
            data = [metrics.model_dump()]
            fields = ["keyword", "volume", "difficulty", "ctr", "priority"]
            headers = ["Keyword", "Volume", "Difficulty", "CTR", "Priority"]
            print_table(data, fields, headers)
        else:
            print_json(metrics)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("suggestions")
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
    try:
        client = get_client()
        suggestions = client.get_keyword_suggestions(keyword)

        # Limit results
        suggestions = suggestions[:limit]

        if table:
            _console.print(VOLUME_NOTE)
            data = [s.model_dump() for s in suggestions]
            fields = ["keyword", "volume", "difficulty"]
            headers = ["Keyword", "Volume", "Difficulty"]
            print_table(data, fields, headers)
        else:
            # Return as list of dicts for JSON
            print_json([s.model_dump() for s in suggestions])

    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("intent")
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
    try:
        client = get_client()
        intent = client.get_search_intent(keyword)

        if table:
            data = [intent.model_dump()]
            fields = ["keyword", "intent_type", "confidence"]
            headers = ["Keyword", "Intent Type", "Confidence"]
            print_table(data, fields, headers)
        else:
            print_json(intent)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("ranking")
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
    try:
        client = get_client()
        keywords = client.get_ranking_keywords(url)

        # Limit results
        keywords = keywords[:limit]

        if table:
            _console.print(VOLUME_NOTE)
            data = [k.model_dump() for k in keywords]
            fields = ["keyword", "position", "volume", "difficulty"]
            headers = ["Keyword", "Position", "Volume", "Difficulty"]
            print_table(data, fields, headers)
        else:
            print_json([k.model_dump() for k in keywords])

    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


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
