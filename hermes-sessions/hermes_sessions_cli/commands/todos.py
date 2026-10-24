"""Todo commands: the final todo list Hermes recorded per session."""
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
    add_time, fetch_limit, print_record, render_table, select_properties,
    to_items, truncate_cells,
)
from ._scope import resolve_session_arg, resolve_time_scope

app = typer.Typer(help="Query todo items from sessions", no_args_is_help=True)

LEAN = [
    ("id", "ID"),
    ("status", "Status"),
    ("content", "Content"),
    ("updated", "Updated"),
]
EXTRA = [("session_id", "Session"), ("position", "Position")]
DETAIL = [
    ("id", "ID"),
    ("session_id", "Session"),
    ("position", "Position"),
    ("status", "Status"),
    ("content", "Content"),
    ("updated_at", "Updated"),
]


@app.command("list")
@command
def list_todos(
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Session ID or title"),
    session_name: Optional[str] = typer.Option(None, "--session-name", "-N", help="Session title (exact, case-insensitive)"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name or absolute path"),
    source: Optional[str] = typer.Option(None, "--source", help="Gateway/runtime source"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Sessions started within this window"),
    date: Optional[str] = typer.Option(None, "--date", help="Sessions started on this local date (YYYY-MM-DD)"),
    date_range: Optional[str] = typer.Option(None, "--date-range", help="Inclusive local range START..END"),
    date_alias: Optional[str] = typer.Option(None, "--date-alias", help="today, yesterday, this_week, last_week"),
    max_chars: int = typer.Option(DEFAULT_MAX_CHARS, "--max-chars", help="Bound on each todo's content preview"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., status:eq:completed)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    List todo items. Hermes rewrites the whole list per call, so this is the
    final state of each session's list.

    Example:
        hermes-sessions todos list --source cron --table
        hermes-sessions todos list -S cron_f2913088764d_20260919_130521
        hermes-sessions todos list --filter "status:eq:pending" --table
        hermes-sessions todos list -S cron_f2913088764d_20260919_130521 --max-chars 60
    """
    since_epoch, date_bounds = resolve_time_scope(since, date, date_range, date_alias)
    try:
        if filter:
            validate_filters(filter)
        client = get_client()
        resolved = resolve_session_arg(client, session_id, session_name, project)
        rows = client.list_todos(
            session_id=resolved, project=project, source=source,
            since=since_epoch, date_bounds=date_bounds,
            limit=fetch_limit(limit, filter), max_chars=max_chars,
        )
        items = to_items(rows)
        if filter:
            items = apply_filters(items, filter)
        items = select_properties(bound_rows(items, limit), properties)

        if table:
            add_time(items, "updated_at", "updated")
            truncate_cells(items, "content")
            render_table(items, LEAN, EXTRA, wide)
        else:
            print_json(items)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
@command
def get_todo(
    reference: str = typer.Argument(..., help="Todo reference: <session-id>:<position>"),
    max_chars: int = typer.Option(DEFAULT_MAX_CHARS, "--max-chars", help="Bound on the todo's content preview"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get one todo item, addressed as <session-id>:<position>.

    Example:
        hermes-sessions todos get cron_f2913088764d_20260919_130521:0 --table
    """
    try:
        record = get_client().get_todo(reference, max_chars=max_chars).model_dump()
        if table:
            print_record(record, DETAIL)
        else:
            print_json(record)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
