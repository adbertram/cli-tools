"""Turn commands: one user prompt and the assistant work it produced."""
COMMAND_CREDENTIALS = {
    "list": ["no_auth"],
    "get": ["no_auth"],
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
    add_time, blank_none, fetch_limit, join_lists, print_record,
    render_table, select_properties, to_items, truncate_cells,
)
from ._scope import resolve_session_arg, resolve_time_scope

app = typer.Typer(help="Query agent turns", no_args_is_help=True)

LEAN = [
    ("id", "ID"),
    ("started", "Started"),
    ("user_prompt", "User Prompt"),
    ("assistant_message_count", "Assistant Msgs"),
    ("tool_call_count", "Tools"),
    ("finish_reason", "Finish"),
]
EXTRA = [
    ("session_id", "Session"),
    ("duration_seconds", "Seconds"),
    ("tools_used", "Tools Used"),
    ("has_errors", "Errors"),
]
DETAIL = [
    ("id", "ID"),
    ("session_id", "Session"),
    ("index", "Index"),
    ("started_at", "Started"),
    ("ended_at", "Ended"),
    ("duration_seconds", "Seconds"),
    ("user_prompt", "User Prompt"),
    ("assistant_message_count", "Assistant Messages"),
    ("tool_call_count", "Tool Calls"),
    ("tools_used", "Tools Used"),
    ("finish_reason", "Finish Reason"),
    ("has_errors", "Has Errors"),
]


@app.command("list")
@command
def list_turns(
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Session ID or title"),
    session_name: Optional[str] = typer.Option(None, "--session-name", "-N", help="Session title (exact, case-insensitive)"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name or absolute path"),
    source: Optional[str] = typer.Option(None, "--source", help="Gateway/runtime source"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Sessions started within this window"),
    date: Optional[str] = typer.Option(None, "--date", help="Sessions started on this local date (YYYY-MM-DD)"),
    date_range: Optional[str] = typer.Option(None, "--date-range", help="Inclusive local range START..END"),
    date_alias: Optional[str] = typer.Option(None, "--date-alias", help="today, yesterday, this_week, last_week"),
    max_chars: int = typer.Option(DEFAULT_MAX_CHARS, "--max-chars", help="Bound on each text preview"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., has_errors:eq:true)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    List turns across the scoped sessions.

    Example:
        hermes-sessions turns list -S cron_f2913088764d_20260919_130521 --table
        hermes-sessions turns list --project CryptoTrader --filter "tool_call_count:gt:3"
    """
    since_epoch, date_bounds = resolve_time_scope(since, date, date_range, date_alias)
    try:
        if filter:
            validate_filters(filter)
        client = get_client()
        resolved = resolve_session_arg(client, session_id, session_name, project)
        rows = client.list_turns(
            session_id=resolved, project=project, source=source,
            since=since_epoch, date_bounds=date_bounds,
            limit=fetch_limit(limit, filter), max_chars=max_chars,
        )
        items = to_items(rows)
        if filter:
            items = apply_filters(items, filter)
        items = select_properties(bound_rows(items, limit), properties)

        if table:
            add_time(items, "started_at", "started")
            join_lists(items, "tools_used")
            blank_none(items, "user_prompt", "finish_reason")
            truncate_cells(items, "user_prompt", "tools_used")
            render_table(items, LEAN, EXTRA, wide)
        else:
            print_json(items)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
@command
def get_turn(
    reference: str = typer.Argument(..., help="Turn reference: <session-id>:<number>"),
    max_chars: int = typer.Option(DEFAULT_MAX_CHARS, "--max-chars", help="Bound on each text preview"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get one turn, addressed as <session-id>:<number>.

    Example:
        hermes-sessions turns get cron_f2913088764d_20260919_130521:2 --table
    """
    try:
        record = get_client().get_turn(reference, max_chars=max_chars).model_dump()
        if table:
            print_record(record, DETAIL)
        else:
            print_json(record)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
