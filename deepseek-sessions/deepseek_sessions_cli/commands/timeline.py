"""Timeline commands for the DeepSeek Sessions CLI."""
COMMAND_CREDENTIALS = {
    "list": ["no_auth"],
    "get": ["no_auth"],
    "consolidated": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import command, handle_error, print_json, print_table

from ..client import ClientError, get_client
from ._render import (
    UNBOUNDED,
    add_time,
    blank_none,
    format_event_type,
    format_status,
    select_properties,
    to_items,
    truncate_value,
)
from .session_arg import require_session_arg, resolve_session_arg

app = typer.Typer(help="View unified activity timeline", no_args_is_help=True)

COLUMNS = [
    "time", "turn_number", "step_number", "model", "type", "agent", "name",
    "status_symbol", "turn_cost_fmt", "session_total_fmt",
    "input_preview", "output_preview",
]
HEADERS = [
    "Time", "Turn", "Step", "Model", "Type", "Agent", "Name",
    "Status", "Cost", "Total", "Input", "Output",
]


def _format_rows(items: List[dict], wide: bool) -> None:
    """Add the display columns the timeline table renders."""
    add_time(items, "timestamp", "time")
    blank_none(items, "model")
    width = 10000 if wide else 50
    for item in items:
        item["type"] = format_event_type(item.get("event_type"))
        item["status_symbol"] = format_status(item.get("status"))
        item["agent"] = item.get("agent_name") or ""
        item["input_preview"] = truncate_value(item.get("input"), width)
        item["output_preview"] = truncate_value(item.get("output"), width)
        turn_cost = item.get("turn_cost")
        session_total = item.get("session_total")
        item["turn_cost_fmt"] = f"{turn_cost:,}" if turn_cost else ""
        item["session_total_fmt"] = f"{session_total:,}" if session_total else ""
        item["turn_number"] = item.get("turn_number") or ""
        item["step_number"] = item.get("step_number") or ""


@app.command("list")
@command
def list_timeline(
    project: str = typer.Option(..., "--project", "-p", help="Project name, path, or directory key (required)"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Session ID or title"),
    session_name: Optional[str] = typer.Option(None, "--session-name", "-N", help="Session title (exact, case-insensitive)"),
    conversation_id: Optional[int] = typer.Option(None, "--conversation-id", "-C", help="Filter to one conversation (requires a session)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show full input/output (no truncation)"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum entries"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    show_thinking: bool = typer.Option(False, "--show-thinking", help="Include assistant reasoning blocks"),
    errors_only: bool = typer.Option(False, "--errors-only", "-e", help="Show only error rows"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., event_type:eq:tool_call)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    Show a unified timeline across a project's sessions.

    Example:
        deepseek-sessions timeline list --project LegoScout --since 1d --table
        deepseek-sessions timeline list -p LegoScout --errors-only --table
        deepseek-sessions timeline list -p LegoScout --filter "event_type:eq:retry"
    """
    try:
        client = get_client()
        resolved = resolve_session_arg(client, session_id, session_name, project=project)

        if conversation_id and not resolved:
            raise typer.BadParameter(
                "--conversation-id requires --session-id or --session-name"
            )

        entries = client.list_timeline(
            project=project,
            # Post-filters narrow the set, so fetch wide and cut at the end.
            limit=UNBOUNDED
            if (conversation_id or errors_only or filter)
            else limit,
            since=since,
            session_id=resolved,
            show_thinking=show_thinking,
        )

        items = to_items(entries)
        if conversation_id:
            items = [item for item in items if item.get("conversation_id") == conversation_id]
        if errors_only:
            items = [item for item in items if item.get("status") == "error"]
        if filter:
            items = apply_filters(items, filter)
        items = select_properties(items[:limit], properties)

        if table:
            _format_rows(items, wide)
            print_table(
                items,
                ["time", "session_id"] + COLUMNS[1:],
                ["Time", "Session"] + HEADERS[1:],
                max_columns=0 if wide else 10,
            )
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def get_timeline(
    session_id: Optional[str] = typer.Argument(None, help="Session ID or title; omit when using --session-name"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name (auto-derived when omitted)"),
    session_name: Optional[str] = typer.Option(None, "--session-name", "-N", help="Session title (exact, case-insensitive)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show full input/output (no truncation)"),
    limit: int = typer.Option(200, "--limit", "-l", help="Maximum entries"),
    show_thinking: bool = typer.Option(False, "--show-thinking", help="Include assistant reasoning blocks"),
):
    """
    Get the timeline for one session.

    Example:
        deepseek-sessions timeline get session-53a213f2-c5ac-4950-a2c7-8011f2281e55 --table
        deepseek-sessions timeline get --session-name "Fix Lego deal run issues" --table
    """
    try:
        client = get_client()
        resolved = require_session_arg(client, session_id, session_name, project=project)
        entries = client.get_timeline(
            session_id=resolved, project=project, limit=limit, show_thinking=show_thinking
        )
        items = to_items(entries)

        if table:
            _format_rows(items, wide)
            print_table(items, COLUMNS, HEADERS, max_columns=0 if wide else 9)
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("consolidated")
@command
def consolidated_timeline(
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Session ID or title"),
    session_name: Optional[str] = typer.Option(None, "--session-name", "-N", help="Session title (exact, case-insensitive)"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name (auto-derived when omitted)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show full input/output (no truncation)"),
    limit: int = typer.Option(500, "--limit", "-l", help="Maximum entries"),
    show_agent_tools: bool = typer.Option(True, "--show-agent-tools/--hide-agent-tools", help="Include tool calls made inside subagent sessions"),
    show_thinking: bool = typer.Option(False, "--show-thinking", help="Include assistant reasoning blocks"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value"),
):
    """
    Show one session plus every subagent it spawned in a single timeline.

    Example:
        deepseek-sessions timeline consolidated -S session-53a213f2-c5ac-4950-a2c7-8011f2281e55 --table
        deepseek-sessions timeline consolidated -S session-53a213f2-c5ac-4950-a2c7-8011f2281e55 --hide-agent-tools
    """
    try:
        client = get_client()
        resolved = require_session_arg(client, session_id, session_name, project=project)
        entries = client.get_timeline(
            session_id=resolved,
            project=project,
            limit=limit,
            show_thinking=show_thinking,
            include_subagents=True,
        )

        items = to_items(entries)
        if not show_agent_tools:
            items = [item for item in items if item.get("event_type") != "subagent_tool"]
        items = items
        if filter:
            items = apply_filters(items, filter)
        items = select_properties(items, None)

        if table:
            _format_rows(items, wide)
            print_table(items, COLUMNS, HEADERS, max_columns=0 if wide else 9)
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
