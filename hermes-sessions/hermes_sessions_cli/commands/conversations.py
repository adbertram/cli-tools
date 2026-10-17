"""Conversation commands: context segments bounded by Hermes compaction."""
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
    add_time, blank_none, fetch_limit, print_record, render_table,
    select_properties, to_items, truncate_cells,
)
from ._scope import resolve_session_arg, resolve_time_scope

app = typer.Typer(help="List conversations within sessions", no_args_is_help=True)

LEAN = [
    ("id", "ID"),
    ("started_by", "Started By"),
    ("started", "Started"),
    ("message_count", "Msgs"),
    ("user_message_count", "User Msgs"),
    ("tool_call_count", "Tools"),
    ("first_user_prompt", "First Prompt"),
]
EXTRA = [("session_id", "Session"), ("ended_at", "Ended")]
DETAIL = [
    ("id", "ID"),
    ("session_id", "Session"),
    ("index", "Index"),
    ("started_by", "Started By"),
    ("started_at", "Started"),
    ("ended_at", "Ended"),
    ("message_count", "Messages"),
    ("user_message_count", "User Messages"),
    ("tool_call_count", "Tool Calls"),
    ("first_user_prompt", "First User Prompt"),
]


@app.command("list")
@command
def list_conversations(
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
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., started_by:eq:compaction)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    List context segments. A session that was never compacted has exactly one.

    Example:
        hermes-sessions conversations list --project LegoScout --table
        hermes-sessions conversations list -S 20260909_202443_f329bcd3
        hermes-sessions conversations list --filter "started_by:eq:compaction"
    """
    since_epoch, date_bounds = resolve_time_scope(since, date, date_range, date_alias)
    try:
        if filter:
            validate_filters(filter)
        client = get_client()
        resolved = resolve_session_arg(client, session_id, session_name, project)
        rows = client.list_conversations(
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
            blank_none(items, "first_user_prompt")
            truncate_cells(items, "first_user_prompt")
            render_table(items, LEAN, EXTRA, wide)
        else:
            print_json(items)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
@command
def get_conversation(
    reference: str = typer.Argument(..., help="Conversation reference: <session-id>:<number>"),
    max_chars: int = typer.Option(DEFAULT_MAX_CHARS, "--max-chars", help="Bound on each text preview"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get one context segment, addressed as <session-id>:<number>.

    Example:
        hermes-sessions conversations get 20260909_202443_f329bcd3:2 --table
    """
    try:
        record = get_client().get_conversation(reference, max_chars=max_chars).model_dump()
        if table:
            print_record(record, DETAIL)
        else:
            print_json(record)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
