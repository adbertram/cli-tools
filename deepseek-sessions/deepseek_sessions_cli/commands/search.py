"""Cross-project search command for the DeepSeek Sessions CLI."""
COMMAND_CREDENTIALS = {
    "run": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import command, handle_error, print_json, print_table

from ..client import ClientError, get_client
from ._render import add_time, blank_none, fetch_limit, render_table, select_properties, to_items

app = typer.Typer(help="Search across session transcripts", no_args_is_help=True)


@app.command("run")
@command
def search(
    query: str = typer.Argument(..., help="Keyword(s) to search for (case-insensitive)"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Restrict to one project"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(20, "--limit", "-l", help="Maximum sessions to return"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d, 30d"),
    max_matches: int = typer.Option(5, "--max-matches", "-m", help="Max snippet matches per session"),
    snippets: bool = typer.Option(False, "--snippets", help="Show the first matching snippet in table mode"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., origin:eq:subagent)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    Search keywords across every dsh session transcript.

    Searches user messages, assistant messages, and tool results. Searches all
    projects by default.

    Example:
        deepseek-sessions search run "legoscout"
        deepseek-sessions search run "timeout" --since 30d --table
        deepseek-sessions search run "auctionzip" --snippets --table
        deepseek-sessions search run "docker" --project CourseCraft
    """
    try:
        results = get_client().search_all(
            query=query,
            project=project,
            limit=fetch_limit(limit, filter),
            since=since,
            max_matches_per_session=max_matches,
        )
        items = to_items(results)
        if filter:
            items = apply_filters(items, filter)
        items = select_properties(items[:limit], properties)

        if table:
            add_time(items, "created_at", "started")
            add_time(items, "last_activity", "last")
            blank_none(items, "model", "origin")
            for item in items:
                item["name"] = item.get("custom_title") or ""
                item["first_match"] = ""
                if snippets and item.get("matches"):
                    first = item["matches"][0]
                    snippet = first.get("snippet", "")
                    if len(snippet) > 100:
                        snippet = snippet[:100] + "..."
                    item["first_match"] = f"[{first.get('role', '?')}] {snippet}"

            lean = [("session_id", "Session ID"), ("name", "Name"),
                    ("project", "Project"), ("last", "Last Activity"),
                    ("match_count", "Matches")]
            extra = [("started", "Started"), ("model", "Model"), ("origin", "Origin")]
            if snippets:
                lean.append(("first_match", "First Match"))
            render_table(items, lean, extra, wide)
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
