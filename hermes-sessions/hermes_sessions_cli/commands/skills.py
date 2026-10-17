"""Skill commands: skill tool loads and slash command invocations."""
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

app = typer.Typer(help="Query skill loads and slash commands", no_args_is_help=True)

LEAN = [
    ("time", "Time"),
    ("kind", "Kind"),
    ("name", "Name"),
    ("status", "Status"),
]
EXTRA = [("id", "ID"), ("session_id", "Session"), ("detail", "Detail")]
DETAIL = [
    ("id", "ID"),
    ("session_id", "Session"),
    ("kind", "Kind"),
    ("name", "Name"),
    ("timestamp", "Timestamp"),
    ("status", "Status"),
    ("detail", "Detail"),
]


@app.command("list")
@command
def list_skills(
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
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., kind:eq:command)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    List skill loads (kind=skill) and slash commands (kind=command).

    Example:
        hermes-sessions skills list --source cron --table
        hermes-sessions skills list -S cron_f2913088764d_20260919_130521
        hermes-sessions skills list --filter "kind:eq:command" --table
    """
    since_epoch, date_bounds = resolve_time_scope(since, date, date_range, date_alias)
    try:
        if filter:
            validate_filters(filter)
        client = get_client()
        resolved = resolve_session_arg(client, session_id, session_name, project)
        rows = client.list_skills(
            session_id=resolved, project=project, source=source,
            since=since_epoch, date_bounds=date_bounds,
            limit=fetch_limit(limit, filter), max_chars=max_chars,
        )
        items = to_items(rows)
        if filter:
            items = apply_filters(items, filter)
        items = select_properties(bound_rows(items, limit), properties)

        if table:
            add_time(items, "timestamp", "time")
            blank_none(items, "detail")
            truncate_cells(items, "detail", "name")
            render_table(items, LEAN, EXTRA, wide)
        else:
            print_json(items)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
@command
def get_skill(
    reference: str = typer.Argument(..., help="Skill record ID: <session-id>:<message-id>:<position>"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Session ID or title to search within"),
    session_name: Optional[str] = typer.Option(None, "--session-name", "-N", help="Session title (exact, case-insensitive)"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name or absolute path"),
    max_chars: int = typer.Option(DEFAULT_MAX_CHARS, "--max-chars", help="Bound on each text preview"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get one skill load or slash command by its record ID.

    Example:
        hermes-sessions skills get cron_f2913088764d_20260919_130521:304951:0 --table
    """
    try:
        client = get_client()
        resolved = resolve_session_arg(client, session_id, session_name, project)
        record = client.get_skill(
            reference, session_id=resolved, project=project, max_chars=max_chars
        ).model_dump()
        if table:
            print_record(record, DETAIL)
        else:
            print_json(record)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
