"""Timeline commands: unified activity views, including consolidated context."""
COMMAND_CREDENTIALS = {
    "list": ["no_auth"],
    "get": ["no_auth"],
    "consolidated": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import apply_filters, validate_filters
from cli_tools_shared.output import command, handle_error, print_json

from ..client import get_client
from ..parsers import DEFAULT_MAX_CHARS
from ._render import (
    bound_rows,
    add_time, blank_none, fetch_limit, render_table, select_properties,
    to_items, truncate_cells,
)
from ._scope import require_session_arg, resolve_session_arg, resolve_time_scope

app = typer.Typer(help="View unified activity timeline", no_args_is_help=True)

LEAN = [
    ("index", "#"),
    ("time", "Time"),
    ("event_type", "Event"),
    ("actor", "Actor"),
    ("tool", "Tool"),
    ("summary", "Summary"),
]
EXTRA = [
    ("session_id", "Session"),
    ("subagent_session", "Subagent"),
    ("status", "Status"),
]


def _render(items, table: bool, wide: bool) -> None:
    if table:
        add_time(items, "timestamp", "time", "%m-%d %H:%M:%S")
        blank_none(items, "tool", "status", "summary", "subagent_session")
        truncate_cells(items, "summary")
        render_table(items, LEAN, EXTRA, wide)
    else:
        print_json(items)


@app.command("list")
@command
def list_timeline(
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Session ID or title"),
    session_name: Optional[str] = typer.Option(None, "--session-name", "-N", help="Session title (exact, case-insensitive)"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name or absolute path"),
    source: Optional[str] = typer.Option(None, "--source", help="Gateway/runtime source"),
    errors_only: bool = typer.Option(False, "--errors-only", help="Only failed tool calls and error events"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Sessions started within this window"),
    date: Optional[str] = typer.Option(None, "--date", help="Sessions started on this local date (YYYY-MM-DD)"),
    date_range: Optional[str] = typer.Option(None, "--date-range", help="Inclusive local range START..END"),
    date_alias: Optional[str] = typer.Option(None, "--date-alias", help="today, yesterday, this_week, last_week"),
    max_chars: int = typer.Option(DEFAULT_MAX_CHARS, "--max-chars", help="Bound on each event summary"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., event_type:eq:tool_call)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    List activity events across the scoped sessions.

    Event types: user_message, assistant_message, command, skill_load,
    tool_call, todo_write, subagent_start, compaction, notice, error.

    Example:
        hermes-sessions timeline list --source cron --limit 20 --table
        hermes-sessions timeline list -S cron_f2913088764d_20260919_130521 --table
        hermes-sessions timeline list --project CryptoTrader --errors-only --table
    """
    since_epoch, date_bounds = resolve_time_scope(since, date, date_range, date_alias)
    try:
        if filter:
            validate_filters(filter)
        client = get_client()
        resolved = resolve_session_arg(client, session_id, session_name, project)
        rows = client.list_timeline(
            session_id=resolved, project=project, source=source,
            since=since_epoch, date_bounds=date_bounds, errors_only=errors_only,
            limit=fetch_limit(limit, filter), max_chars=max_chars,
        )
        items = to_items(rows)
        if filter:
            items = apply_filters(items, filter)
        _render(select_properties(bound_rows(items, limit), properties), table, wide)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
@command
def get_timeline(
    session_id: Optional[str] = typer.Argument(None, help="Session ID or title; omit when using --session-name"),
    session_name: Optional[str] = typer.Option(None, "--session-name", "-N", help="Session title (exact, case-insensitive)"),
    errors_only: bool = typer.Option(False, "--errors-only", help="Only failed tool calls and error events"),
    max_chars: int = typer.Option(DEFAULT_MAX_CHARS, "--max-chars", help="Bound on each event summary"),
    limit: int = typer.Option(200, "--limit", "-l", help="Maximum events"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    Get the full event timeline of one session.

    Example:
        hermes-sessions timeline get cron_f2913088764d_20260919_130521 --table
        hermes-sessions timeline get --session-name "ATA Blog daily comment management" --errors-only
    """
    try:
        client = get_client()
        resolved = require_session_arg(client, session_id, session_name)
        rows = client.get_timeline(
            resolved, errors_only=errors_only, limit=limit, max_chars=max_chars
        )
        _render(select_properties(to_items(rows), properties), table, wide)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))


@app.command("consolidated")
@command
def consolidated_timeline(
    session_id: Optional[str] = typer.Argument(None, help="Session ID or title; omit when using --session-name"),
    session_name: Optional[str] = typer.Option(None, "--session-name", "-N", help="Session title (exact, case-insensitive)"),
    subagents: bool = typer.Option(True, "--subagents/--no-subagents", help="Merge in the session's subagent runs"),
    max_chars: int = typer.Option(DEFAULT_MAX_CHARS, "--max-chars", help="Bound on each event summary"),
    limit: int = typer.Option(200, "--limit", "-l", help="Maximum merged events"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    Merge a session and its subagent runs into one bounded chronological view.

    The view is bounded twice: --limit caps the merged event count and
    --max-chars caps every event summary, so it never becomes a transcript dump.

    Example:
        hermes-sessions timeline consolidated cron_b03d38d15003_20260918_090207 --table
        hermes-sessions timeline consolidated cron_b03d38d15003_20260918_090207 --limit 40 --max-chars 80
    """
    try:
        client = get_client()
        resolved = require_session_arg(client, session_id, session_name)
        rows = client.consolidated_timeline(
            resolved, limit=limit, max_chars=max_chars, include_subagents=subagents
        )
        _render(select_properties(to_items(rows), properties), table, wide)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
