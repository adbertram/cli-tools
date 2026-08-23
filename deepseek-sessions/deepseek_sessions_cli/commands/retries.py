"""Retry commands for the DeepSeek Sessions CLI.

dsh records every retryable provider failure as `llm/retry` (with the failure
code, the attempt number, and the backoff delay) and the moment the retry
actually begins as `llm/retry-started`. A row with `started: false` means the
retry was scheduled but the session ended before it ran.
"""
COMMAND_CREDENTIALS = {
    "list": ["no_auth"],
    "get": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import command, handle_error, print_json, print_table

from ..client import ClientError, get_client
from ..parsers import format_local_time
from ._render import add_time, blank_none, fetch_limit, render_table, select_properties, to_items
from .session_arg import resolve_session_arg

app = typer.Typer(help="Query LLM retries and their failure codes", no_args_is_help=True)


@app.command("list")
@command
def list_retries(
    project: str = typer.Option(..., "--project", "-p", help="Project name, path, or directory key (required)"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Session ID or title"),
    session_name: Optional[str] = typer.Option(None, "--session-name", "-N", help="Session title (exact, case-insensitive)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., error_code:eq:TIMEOUT)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    List retryable provider failures in a project.

    Example:
        deepseek-sessions retries list --project LegoScout --table
        deepseek-sessions retries list -p LegoScout --filter "error_code:eq:TIMEOUT"
        deepseek-sessions retries list -p LegoScout --filter "started:eq:false"
    """
    try:
        client = get_client()
        resolved = resolve_session_arg(client, session_id, session_name, project=project)
        retries = client.list_retries(
            project=project, session_id=resolved,
            limit=fetch_limit(limit, filter), since=since
        )
        items = to_items(retries)
        if filter:
            items = apply_filters(items, filter)
        items = select_properties(items[:limit], properties)

        if table:
            add_time(items, "timestamp", "time")
            blank_none(items, "provider", "error_code")
            for item in items:
                delay = item.get("delay_ms")
                item["delay"] = f"{delay / 1000:.1f}s" if delay else ""
                item["attempt_fmt"] = f"{item.get('attempt', 0)}/{item.get('max_retries', 0)}"
            render_table(
                items,
                [("time", "Time"), ("session_id", "Session"), ("error_code", "Code"),
                 ("attempt_fmt", "Attempt"), ("delay", "Delay"), ("started", "Started")],
                [("turn", "Turn"), ("provider", "Provider"), ("mode", "Mode"),
                 ("error_message", "Message")],
                wide,
            )
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def get_retry(
    retry_id: str = typer.Argument(..., help="Retry ID (dsh retryId)"),
    project: str = typer.Option(..., "--project", "-p", help="Project name, path, or directory key (required)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for one retry.

    Example:
        deepseek-sessions retries get 79da67c3-9ac4-463e-b2af-7f20b4f2b416 -p LegoScout
    """
    try:
        row = next(
            (item for item in get_client().list_retries(project, limit=1000000) if item.id == retry_id),
            None,
        )
        if row is None:
            print_json({"error": f"Retry not found: {retry_id}"})
            raise typer.Exit(1)

        if table:
            rows = [
                {"field": "ID", "value": row.id},
                {"field": "Session", "value": row.session_id},
                {"field": "Time", "value": format_local_time(row.timestamp)},
                {"field": "Turn / Step", "value": f"{row.turn} / {row.step}"},
                {"field": "Provider", "value": row.provider or "N/A"},
                {"field": "Mode", "value": row.mode or "N/A"},
                {"field": "Attempt", "value": f"{row.attempt}/{row.max_retries}"},
                {"field": "Delay", "value": f"{row.delay_ms / 1000:.2f}s" if row.delay_ms else "N/A"},
                {"field": "Error Code", "value": row.error_code or "N/A"},
                {"field": "Error Message", "value": row.error_message or "N/A"},
                {"field": "Started", "value": str(row.started)},
                {"field": "Started At", "value": format_local_time(row.started_at or "") or "N/A"},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(row.model_dump())

    except typer.Exit:
        raise
    except ClientError as e:
        raise typer.Exit(handle_error(e))
