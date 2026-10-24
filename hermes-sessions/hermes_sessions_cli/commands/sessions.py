"""Session commands: list, get, and search Hermes sessions."""
COMMAND_CREDENTIALS = {
    "list": ["no_auth"],
    "get": ["no_auth"],
    "search": ["no_auth"],
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
    add_time,
    add_tokens,
    blank_none,
    fetch_limit,
    print_record,
    render_table,
    select_properties,
    to_items,
    truncate_cells,
)
from ._scope import require_session_arg, resolve_time_scope

app = typer.Typer(help="List, get, and search sessions", no_args_is_help=True)

LEAN = [
    ("title", "Title"),
    ("id", "ID"),
    ("project", "Project"),
    ("source", "Source"),
    ("started", "Started"),
    ("message_count", "Msgs"),
    ("tool_call_count", "Tools"),
    ("effective", "Effective"),
]
EXTRA = [
    ("model", "Model"),
    ("profile", "Profile"),
    ("end_reason", "End Reason"),
    ("subagent_count", "Subagents"),
    ("in_tok", "In Tok"),
    ("out_tok", "Out Tok"),
    ("cache_read", "Cache Read"),
    ("reasoning", "Reasoning"),
]
DETAIL = [
    ("id", "ID"),
    ("title", "Title"),
    ("title_source", "Title Source"),
    ("project", "Project"),
    ("cwd", "CWD"),
    ("source", "Source"),
    ("profile", "Profile"),
    ("model", "Model"),
    ("created_at", "Created"),
    ("last_activity", "Last Activity"),
    ("ended_at", "Ended"),
    ("end_reason", "End Reason"),
    ("parent_session", "Parent Session"),
    ("is_subagent", "Is Subagent"),
    ("subagent_count", "Subagents"),
    ("message_count", "Messages"),
    ("turn_count", "Turns"),
    ("conversation_count", "Conversations"),
    ("tool_call_count", "Tool Calls"),
    ("todo_count", "Todos"),
    ("skill_count", "Skills"),
    ("error_count", "Errors"),
    ("compacted_message_count", "Compacted Messages"),
    ("tool_names", "Tools Used"),
    ("effective_tokens", "Effective Tokens"),
    ("estimated_cost_usd", "Estimated Cost USD"),
    ("first_user_prompt", "First User Prompt"),
    ("last_assistant_message", "Last Assistant Message"),
]


def _render_rows(items, wide: bool) -> None:
    add_tokens(items)
    add_time(items, "created_at", "started")
    blank_none(items, "title", "model", "profile", "end_reason")
    truncate_cells(items, "title", "model")
    render_table(items, LEAN, EXTRA, wide)


@app.command("list")
@command
def list_sessions(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name or absolute path"),
    source: Optional[str] = typer.Option(None, "--source", help="Gateway/runtime source: cli, cron, slack, subagent, webui, email"),
    subagents: bool = typer.Option(True, "--subagents/--no-subagents", help="Include delegated subagent sessions"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Started within this window: 30m, 5h, 7d, 2w"),
    date: Optional[str] = typer.Option(None, "--date", help="Sessions started on this local date (YYYY-MM-DD)"),
    date_range: Optional[str] = typer.Option(None, "--date-range", help="Inclusive local range START..END (YYYY-MM-DD..YYYY-MM-DD)"),
    date_alias: Optional[str] = typer.Option(None, "--date-alias", help="One of today, yesterday, this_week, last_week"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., source:eq:cron)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    List sessions newest-first. With no --project, covers every workspace.

    Example:
        hermes-sessions sessions list --table
        hermes-sessions sessions list --source cron --limit 5
        hermes-sessions sessions list --project LegoScout --no-subagents
        hermes-sessions sessions list --date-alias yesterday --table
        hermes-sessions sessions list --filter "tool_call_count:gt:10"
    """
    since_epoch, date_bounds = resolve_time_scope(since, date, date_range, date_alias)
    try:
        if filter:
            validate_filters(filter)
        rows = get_client().list_sessions(
            project=project,
            source=source,
            include_subagents=subagents,
            since=since_epoch,
            date_bounds=date_bounds,
            limit=fetch_limit(limit, filter),
        )
        items = to_items(rows)
        if filter:
            items = apply_filters(items, filter)
        items = select_properties(bound_rows(items, limit), properties)

        if table:
            _render_rows(items, wide)
        else:
            print_json(items)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
@command
def get_session(
    session_id: Optional[str] = typer.Argument(None, help="Session ID or title; omit when using --session-name"),
    session_name: Optional[str] = typer.Option(None, "--session-name", "-N", help="Session title (exact, case-insensitive)"),
    max_chars: int = typer.Option(DEFAULT_MAX_CHARS, "--max-chars", help="Bound on each text preview"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get one session's metadata and counts. Never prints message bodies.

    Example:
        hermes-sessions sessions get cron_f2913088764d_20260919_130521 --table
        hermes-sessions sessions get --session-name "ATA Blog daily comment management"
    """
    try:
        client = get_client()
        resolved = require_session_arg(client, session_id, session_name)
        record = client.get_session(resolved, max_chars=max_chars).model_dump()
        if table:
            print_record(record, DETAIL)
        else:
            print_json(record)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))


@app.command("search")
@command
def search_sessions(
    query: str = typer.Argument(..., help="Substring to match against session titles"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name or absolute path"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Started within this window: 30m, 5h, 7d"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    Search session titles. Use `search run` for full-text transcript search.

    Example:
        hermes-sessions sessions search "comment management" --table
        hermes-sessions sessions search "legoscout" --since 7d
    """
    since_epoch, _ = resolve_time_scope(since)
    try:
        rows = get_client().search_sessions(
            query=query, project=project, since=since_epoch, limit=limit
        )
        items = select_properties(to_items(rows), properties)
        if table:
            _render_rows(items, wide)
        else:
            print_json(items)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
