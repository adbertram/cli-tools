"""Subagent activity commands: delegated Hermes subagent runs."""
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

app = typer.Typer(help="Query subagent invocations", no_args_is_help=True)

LEAN = [
    ("id", "Child Session"),
    ("started", "Started"),
    ("status", "Status"),
    ("tool_call_count", "Tools"),
    ("label", "Delegated Goal"),
]
EXTRA = [
    ("parent_session", "Parent Session"),
    ("model", "Model"),
    ("message_count", "Msgs"),
    ("duration_seconds", "Seconds"),
    ("effective_tokens", "Effective"),
    ("result", "Result"),
]
DETAIL = [
    ("id", "ID"),
    ("parent_session", "Parent Session"),
    ("child_session", "Child Session"),
    ("label", "Delegated Goal"),
    ("status", "Status"),
    ("started_at", "Started"),
    ("completed_at", "Completed"),
    ("duration_seconds", "Seconds"),
    ("model", "Model"),
    ("message_count", "Messages"),
    ("tool_call_count", "Tool Calls"),
    ("effective_tokens", "Effective Tokens"),
    ("result", "Result"),
]


@app.command("list")
@command
def list_subagent_activity(
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Parent session ID or title"),
    session_name: Optional[str] = typer.Option(None, "--session-name", "-N", help="Parent session title (exact, case-insensitive)"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name or absolute path"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Started within this window"),
    date: Optional[str] = typer.Option(None, "--date", help="Started on this local date (YYYY-MM-DD)"),
    date_range: Optional[str] = typer.Option(None, "--date-range", help="Inclusive local range START..END"),
    date_alias: Optional[str] = typer.Option(None, "--date-alias", help="today, yesterday, this_week, last_week"),
    max_chars: int = typer.Option(DEFAULT_MAX_CHARS, "--max-chars", help="Bound on each text preview"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., status:eq:agent_close)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    List delegated subagent runs. With -S, only the children of that parent.

    Example:
        hermes-sessions subagent-activity list --table
        hermes-sessions subagent-activity list -S cron_b03d38d15003_20260918_090207
        hermes-sessions subagent-activity list --filter "tool_call_count:gt:5" --table
    """
    since_epoch, date_bounds = resolve_time_scope(since, date, date_range, date_alias)
    try:
        if filter:
            validate_filters(filter)
        client = get_client()
        resolved = resolve_session_arg(client, session_id, session_name, project)
        rows = client.list_subagent_activity(
            session_id=resolved, project=project, since=since_epoch,
            date_bounds=date_bounds, limit=fetch_limit(limit, filter),
            max_chars=max_chars,
        )
        items = to_items(rows)
        if filter:
            items = apply_filters(items, filter)
        items = select_properties(bound_rows(items, limit), properties)

        if table:
            add_time(items, "started_at", "started")
            blank_none(items, "label", "result", "model", "parent_session", "duration_seconds")
            truncate_cells(items, "label", "result")
            render_table(items, LEAN, EXTRA, wide)
        else:
            print_json(items)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
@command
def get_subagent_activity(
    child_session_id: str = typer.Argument(..., help="Subagent (child) session ID"),
    max_chars: int = typer.Option(DEFAULT_MAX_CHARS, "--max-chars", help="Bound on each text preview"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get one subagent run by its child session ID.

    Example:
        hermes-sessions subagent-activity get 20260918_090230_c0952c --table
    """
    try:
        record = get_client().get_subagent_activity(
            child_session_id, max_chars=max_chars
        ).model_dump()
        if table:
            print_record(record, DETAIL)
        else:
            print_json(record)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
