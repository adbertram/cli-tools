"""Suggest command for querying autocomplete suggestions."""
from typing import List, Optional

import typer

from ..client import get_client
from ..models import Source, SuggestionRow, flatten_recursive_suggestions
from cli_tools_shared.output import handle_error, print_json, print_table, print_info

app = typer.Typer(help="Query autocomplete suggestions from search engines")


@app.command("query")
def suggest_query(
    query: str = typer.Argument(..., help="Search query to get suggestions for"),
    source: List[Source] = typer.Option(
        [Source.GOOGLE],
        "--source",
        "-s",
        help="Sources to query (google, youtube, bing, amazon, ddg). Can be repeated.",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(
        100, "--limit", "-l", help="Maximum suggestions per source"
    ),
    filter_text: Optional[str] = typer.Option(
        None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"
    ),
    recurse: bool = typer.Option(
        False, "--recurse", "-r", help="Recursively query suggestions of suggestions"
    ),
    depth: int = typer.Option(
        1, "--depth", "-d", help="Recursion depth (how many levels deep to query)"
    ),
    recurse_limit: int = typer.Option(
        5,
        "--recurse-limit",
        help="Max suggestions to recurse into per level (default: 5)",
    ),
):
    """Get autocomplete suggestions for a query.

    Examples:
        keywords suggest query "python"
        keywords suggest query "best laptop" --source google --source youtube
        keywords suggest query "seo tools" -s google -s amazon -t
        keywords suggest query "python" --filter "beginner"
        keywords suggest query "python" --recurse --depth 2
        keywords suggest query "seo" -r -d 1 --recurse-limit 3 -t
    """
    try:
        client = get_client()

        if recurse:
            # Recursive mode: query one source at a time and build tree
            if len(source) > 1:
                print_info(
                    f"Recursive mode uses first source only ({source[0].value})"
                )

            result = client.get_suggestions_recursive(
                query,
                source[0],
                depth=depth,
                limit_per_level=recurse_limit,
            )

            if table:
                # Flatten recursive results for table display
                rows = flatten_recursive_suggestions(
                    result.suggestions, result.source.value, parent=query
                )
                if rows:
                    print_table(
                        rows,
                        ["depth", "parent", "suggestion"],
                        ["Depth", "Parent Query", "Suggestion"],
                    )
                else:
                    print_table(
                        [],
                        ["depth", "parent", "suggestion"],
                        ["Depth", "Parent Query", "Suggestion"],
                    )
            else:
                print_json(result)
        else:
            # Standard mode: query all sources
            results = client.get_suggestions(query, list(source))

            # Apply limit per source
            for result in results:
                if len(result.suggestions) > limit:
                    result.suggestions = result.suggestions[:limit]
                    result.count = limit

            # Apply filter if specified
            if filter_text:
                filter_lower = filter_text.lower()
                for result in results:
                    result.suggestions = [
                        s for s in result.suggestions if filter_lower in s.lower()
                    ]
                    result.count = len(result.suggestions)

            if table:
                # Flatten for table display
                rows: List[SuggestionRow] = []
                for result in results:
                    for suggestion in result.suggestions:
                        rows.append(
                            SuggestionRow(
                                source=result.source.value, suggestion=suggestion
                            )
                        )
                if rows:
                    print_table(
                        rows, ["source", "suggestion"], ["Source", "Suggestion"]
                    )
                else:
                    print_table(
                        [], ["source", "suggestion"], ["Source", "Suggestion"]
                    )
            else:
                print_json(results)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("sources")
def list_sources(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """List available autocomplete sources.

    Examples:
        keywords suggest sources
        keywords suggest sources --table
    """
    sources = [
        {"name": "google", "description": "Google web search suggestions"},
        {"name": "youtube", "description": "YouTube video search suggestions"},
        {"name": "bing", "description": "Bing web search suggestions"},
        {"name": "amazon", "description": "Amazon product search suggestions"},
        {"name": "ddg", "description": "DuckDuckGo web search suggestions"},
    ]

    if table:
        print_table(sources, ["name", "description"], ["Source", "Description"])
    else:
        print_json(sources)
