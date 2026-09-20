"""Search commands: full-text search across Hermes message content."""
COMMAND_CREDENTIALS = {
    "run": ["no_auth"],
}

from typing import Optional

import typer
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import command, handle_error, print_json

from ..client import get_client
from ..parsers import DEFAULT_MAX_CHARS
from ._render import (
    add_time, blank_none, render_table, select_properties, to_items,
    truncate_cells,
)
from ._scope import resolve_session_arg, resolve_time_scope

app = typer.Typer(help="Search keywords across session transcripts", no_args_is_help=True)

LEAN = [
    ("time", "Time"),
    ("session_id", "Session"),
    ("role", "Role"),
    ("tool", "Tool"),
    ("snippet", "Snippet"),
]
EXTRA = [("id", "Message ID"), ("session_title", "Title"), ("project", "Project")]


@app.command("run")
@command
def run_search(
    query: str = typer.Argument(..., help="FTS5 query (e.g., timeout, \"rate limit\", legoscout*)"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Session ID or title"),
    session_name: Optional[str] = typer.Option(None, "--session-name", "-N", help="Session title (exact, case-insensitive)"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name or absolute path"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Messages newer than this window: 30m, 5h, 7d"),
    max_chars: int = typer.Option(DEFAULT_MAX_CHARS, "--max-chars", help="Bound on each snippet"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    Search message content through the Hermes FTS5 index.

    Example:
        hermes-sessions search run "timeout" --limit 10 --table
        hermes-sessions search run "legoscout" --since 7d
        hermes-sessions search run "rate limit" --project CryptoTrader --table
    """
    since_epoch, _ = resolve_time_scope(since)
    try:
        client = get_client()
        resolved = resolve_session_arg(client, session_id, session_name, project)
        rows = client.search_messages(
            query, project=project, session_id=resolved,
            since=since_epoch, limit=limit, max_chars=max_chars,
        )
        items = select_properties(to_items(rows), properties)
        if table:
            add_time(items, "timestamp", "time")
            blank_none(items, "tool", "snippet", "session_title")
            truncate_cells(items, "snippet", "session_title")
            render_table(items, LEAN, EXTRA, wide)
        else:
            print_json(items)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
